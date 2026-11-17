import json
import os
from pathlib import Path
import subprocess

import pytest

from dsh.office.errors import OfficeKitError
from dsh.office.font_volume import FontVolume, _fstat, identity


def asset(volume):
    return next(iter(volume.assets.values()))


def test_ordered_discovery_preserves_physical_characters_and_deduplicates(tmp_path):
    folder = tmp_path / 'fonts'
    folder.mkdir()
    for name in ('z.otf', 'a.TTF', 'ignored.txt', 'b.ttc'):
        (folder / name).write_bytes(name.encode('utf-8'))
    volume = FontVolume([str(folder), str(folder / 'a.TTF')])
    assert [Path(row.path).name for row in volume.assets.values()] == ['a.TTF', 'b.ttc', 'z.otf']
    assert volume.paths == ['/physical/' + row.path for row in volume.assets.values()]
    assert all('/' not in route and '\\' not in route for route in volume.assets)
    assert volume.manifest() == dict(files=volume.files, directories={})


def test_non_fonts_and_absent_directories_do_not_consume_capacity(tmp_path):
    (tmp_path / 'ignored.bin').write_bytes(b'x')
    assert FontVolume([str(tmp_path), str(tmp_path / 'absent')], max_files=0).paths == []


def test_file_limit_counts_oversized_candidates_before_parsing(tmp_path):
    for name in ('one.ttf', 'two.ttf'):
        (tmp_path / name).write_bytes(b'too large')
    with pytest.raises(OfficeKitError, match='exceeds maxFontFiles'):
        FontVolume([str(tmp_path)], max_files=1, max_file_bytes=1)


def test_read_is_bounded_and_releases_descriptor(tmp_path):
    path = tmp_path / 'original.ttf'
    path.write_bytes(b'abcdef')
    entry = asset(FontVolume([str(path)]))
    with entry.open('rb') as stream:
        descriptor = stream.fileno()
        assert stream.read(2) == b'ab'
        assert stream.read(-1) == b'cdef'
        assert stream.read(100) == b''
    with pytest.raises(OSError):
        os.fstat(descriptor)
    entry.validate()


def test_read_rejects_wrong_mode_and_oversized_font(tmp_path):
    path = tmp_path / 'original.ttf'
    path.write_bytes(b'abcdef')
    entry = asset(FontVolume([str(path)], max_file_bytes=2))
    with pytest.raises(ValueError, match='read-only'):
        entry.open('wb')
    with pytest.raises(OfficeKitError, match='maxFontFileBytes'):
        with entry.open('rb'):
            pass


@pytest.mark.parametrize('kind', ['deleted', 'changed', 'replaced', 'directory'])
def test_source_changes_rejected_before_read_and_before_publish(tmp_path, kind):
    path = tmp_path / 'original.ttf'
    path.write_bytes(b'abcdef')
    volume = FontVolume([str(path)])
    entry = asset(volume)
    if kind == 'changed':
        before = path.stat()
        path.write_bytes(b'ABCDEF')
        os.utime(str(path), ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        path.unlink()
        if kind == 'replaced':
            path.write_bytes(b'abcdef')
        elif kind == 'directory':
            path.mkdir()
    def read():
        with entry.open('rb'):
            pass
    for operation in (read, lambda: volume.validate([dict(path=volume.paths[0])])):
        with pytest.raises(OfficeKitError, match='system font changed') as caught:
            operation()
        assert caught.value.code == 'failed'


@pytest.mark.parametrize('kind', ['grown', 'truncated', 'same-size'])
def test_changes_during_opened_read_are_rejected_and_close_descriptor(tmp_path, kind):
    path = tmp_path / 'original.ttf'
    path.write_bytes(b'abcdef')
    entry = asset(FontVolume([str(path)]))
    with pytest.raises(OfficeKitError, match='system font changed'):
        with entry.open('rb') as stream:
            descriptor = stream.fileno()
            assert stream.read(2) == b'ab'
            path.write_bytes({'grown': b'abcdefgh', 'truncated': b'a', 'same-size': b'ABCDEF'}[kind])
            while stream.read(2):
                pass
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_unknown_snapshot_file_rejected(tmp_path):
    with pytest.raises(OfficeKitError, match='unknown source'):
        FontVolume([str(tmp_path)]).validate([dict(path='/not-owned.ttf')])


def test_discovery_observes_cancellation_before_io(tmp_path):
    reason = RuntimeError('scan cancelled')
    def check():
        raise reason
    with pytest.raises(RuntimeError) as caught:
        FontVolume([str(tmp_path)], check=check)
    assert caught.value is reason


@pytest.mark.skipif(os.name != 'nt', reason='Windows handle identity')
def test_opened_handle_matches_actual_node_bigint_stat(tmp_path):
    executable = os.environ.get('DSH_TEST_OFFICE_NODE')
    if not executable:
        pytest.skip('Set DSH_TEST_OFFICE_NODE for independent Node identity comparison.')
    path = tmp_path / 'font.ttf'
    path.write_bytes(b'opened font bytes')
    code = "const fs=require('fs'),fd=fs.openSync(process.argv[1],'r'),s=fs.fstatSync(fd,{bigint:true});console.log(JSON.stringify({dev:String(s.dev),ino:String(s.ino),size:Number(s.size),mtimeNs:String(s.mtimeNs),ctimeNs:String(s.ctimeNs)}));fs.closeSync(fd)"
    expected = json.loads(subprocess.check_output([executable, '-e', code, str(path)], text=True))
    with path.open('rb') as stream:
        assert identity(_fstat(stream.fileno())) == expected


@pytest.mark.asyncio
async def test_actual_carrier_font_identity_failure_does_not_wait_for_timeout(tmp_path):
    from dsh.office.browser_carrier import BrowserCarrier
    executable = os.environ.get('DSH_TEST_OFFICE_BROWSER')
    if not executable:
        pytest.skip('Set DSH_TEST_OFFICE_BROWSER for the actual HTTP carrier check.')
    path = tmp_path / 'font.ttf'
    path.write_bytes(b'original')
    volume = FontVolume([str(path)])
    path.write_bytes(b'changed')
    profiles = tmp_path / 'profiles'
    profiles.mkdir()
    carrier = BrowserCarrier(executable, temporary_directory=str(profiles))
    try:
        route = next(iter(volume.assets))
        with pytest.raises(OfficeKitError, match='system font changed'):
            await carrier.run("fetch(" + json.dumps(route) + ").then(r=>r.arrayBuffer()).then(b=>self.postMessage(b))", volume.assets, timeout=10)
        assert not list(profiles.iterdir())
    finally:
        await carrier.close()
