"""Real Microsoft SDK bytes and rejected input/layout damage; no Win7 certification."""
import json
import os
from pathlib import Path
import shutil

import pytest

from scripts import build_portable as build
from scripts.ucrt_inputs import bundle_ucrt, validate_bundled_ucrt, verify_pinned_ucrt


ROOT = Path(__file__).resolve().parents[1]
DAMAGES = ('missing-binary', 'binary', 'manifest', 'license', 'redist', 'hardlink')


def test_actual_sdk_files_keep_exact_identity_and_app_local_layout(tmp_path):
    manifest = verify_pinned_ucrt(ROOT)
    assert manifest['version'] == '10.0.14393.795'
    assert manifest['architecture'] == 'x64'
    assert manifest['compatibility']['win7Execution'] == 'deferred; not certified'
    distribution = tmp_path / 'distribution'
    distribution.mkdir()
    assert bundle_ucrt(ROOT, distribution) == manifest
    assert validate_bundled_ucrt(distribution, manifest) == manifest
    assert len(list(distribution.glob('*.dll'))) == 41
    for row in manifest['files']:
        assert (distribution / row['name']).read_bytes() == (ROOT / 'vendor/ucrt/x64' / row['name']).read_bytes()
    assert (distribution / 'UCRT-LICENSE.rtf').read_bytes() == (ROOT / 'vendor/ucrt/SDK-LICENSE.rtf').read_bytes()


@pytest.mark.parametrize('damage', DAMAGES)
def test_bad_ucrt_input_cannot_replace_previous_release(tmp_path, monkeypatch, damage):
    fixture = tmp_path / 'fixture'
    directory = fixture / 'vendor/ucrt'
    shutil.copytree(ROOT / 'vendor/ucrt', directory)
    shutil.copytree(ROOT / 'dsh/fs/tool_fs_search/bin', fixture / 'dsh/fs/tool_fs_search/bin')
    binary = directory / 'x64/ucrtbase.dll'
    if damage == 'missing-binary':
        binary.unlink()
    elif damage == 'binary':
        binary.write_bytes(b'unapproved binary')
    elif damage == 'manifest':
        (directory / 'ucrt-input.json').write_text('{}', encoding='utf-8')
    elif damage == 'license':
        (directory / 'SDK-LICENSE.rtf').write_bytes(b'changed license')
    elif damage == 'redist':
        (directory / 'REDIST.html').unlink()
    else:
        os.link(str(binary), str(tmp_path / 'foreign-link'))
    distribution = tmp_path / 'previous'
    distribution.mkdir()
    sentinel = distribution / 'sentinel'
    sentinel.write_bytes(b'previous accepted distribution')
    archive = tmp_path / 'previous.zip'
    archive.write_bytes(b'previous accepted ZIP')
    monkeypatch.setattr(build, 'ROOT_DIR', str(fixture))
    with pytest.raises((ValueError, FileNotFoundError)):
        build.assemble_portable(str(distribution), str(archive))
    assert sentinel.read_bytes() == b'previous accepted distribution'
    assert archive.read_bytes() == b'previous accepted ZIP'


@pytest.mark.parametrize('damage', ('missing', 'binary', 'relocated', 'manifest', 'license', 'redist', 'hardlink'))
def test_extracted_ucrt_damage_is_rejected(tmp_path, damage):
    manifest = bundle_ucrt(ROOT, tmp_path)
    binary = tmp_path / 'ucrtbase.dll'
    if damage == 'missing':
        binary.unlink()
    elif damage == 'binary':
        binary.write_bytes(b'unapproved binary')
    elif damage == 'relocated':
        (tmp_path / 'DLLs').mkdir()
        binary.rename(tmp_path / 'DLLs/ucrtbase.dll')
    elif damage == 'manifest':
        (tmp_path / 'ucrt-input.json').write_text('{}', encoding='utf-8')
    elif damage == 'license':
        (tmp_path / 'UCRT-LICENSE.rtf').unlink()
    elif damage == 'redist':
        (tmp_path / 'UCRT-REDIST.html').write_bytes(b'changed list')
    else:
        os.link(str(binary), str(tmp_path / 'foreign-link'))
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_bundled_ucrt(tmp_path, manifest)


@pytest.mark.parametrize('damage', ('missing-proof', 'missing-provenance', 'wrong-version', 'missing-file', 'changed-hash'))
def test_current_release_requires_complete_ucrt_receipt(tmp_path, damage):
    from test_current_release_gate import GATE, extracted_receipt
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing-proof':
        del report['ucrtInput']
    elif damage == 'missing-provenance':
        del report['provenance']['ucrt_input']
    elif damage == 'wrong-version':
        report['ucrtInput']['version'] = 'modern host UCRT'
    elif damage == 'missing-file':
        report['ucrtInput']['files'].pop()
    else:
        report['ucrtInput']['files'][0]['sha256'] = '0' * 64
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='app-local UCRT'):
        GATE.validate_extracted(path, archive, candidate)
