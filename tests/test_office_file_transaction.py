import asyncio
import json
import os
from pathlib import Path
import subprocess
import threading
import time

import pytest

from dsh.core.abort import AbortController
from dsh.office.errors import OfficeKitError
from dsh.office.file_transaction import FileExport, ImageExport, disk_call, read_document


def test_public_source_file_failures_and_bounded_reads(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = root / 'reference'
    node = os.environ.get('DSH_TEST_OFFICE_NODE')
    if not node or not source.exists():
        pytest.skip('Explicit pinned Office Source/Node qualification inputs required.')
    result = subprocess.run([node, str(root / 'scripts/oracles/rc022_office_files.mjs'), str(source), str(tmp_path / 'source')],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
    assert result.returncode == 0, result.stdout.decode('utf-8', 'replace')
    expected = json.loads((tmp_path / 'source/report.json').read_text(encoding='utf-8'))['rows']
    actual = []
    for row in expected:
        name = row['name']
        run = tmp_path / name
        run.mkdir()
        controller = AbortController()
        if name.startswith('read-'):
            content = {'read-exact': b'1234', 'read-empty-output': b'', 'read-empty-input': b'', 'read-output-limit': b'12345'}[name]
            path = run / 'input'
            path.write_bytes(content)
            try:
                value = dict(text=read_document(str(path), 4, controller.signal, 'output' if name in ('read-empty-output', 'read-output-limit') else 'input').decode('utf-8'))
            except OfficeKitError as cause:
                value = dict(code=cause.code, message=cause.message)
            actual.append(dict(name=name, result=value))
            continue
        input_path, output = run / 'input.docx', run / 'output.txt'
        if name == 'missing-output-parent':
            output = run / 'missing/output.txt'
        if 'missing-input' not in name:
            input_path.write_bytes(b'' if name == 'empty' else b'12345' if name == 'oversized' else b'123')
        if 'existing-output' in name:
            output.write_text('KEEP', encoding='utf-8')
        if name == 'output-directory':
            output.mkdir()
        if name == 'aborted':
            controller.abort('raw abort')
        transaction = FileExport(str(output))
        try:
            controller.signal.throwIfAborted()
            transaction.open()
            read_document(str(input_path), 4, controller.signal)
            value = dict(unexpected=True)
        except OfficeKitError as cause:
            value = dict(code=cause.code, message=cause.message)
        except OSError:
            value = dict(os=True)
        except Exception as cause:
            assert getattr(cause, 'value', None) == 'raw abort'
            value = dict(abort='raw abort')
        finally:
            transaction.close()
        actual.append(dict(name=name, result=value, output='directory' if output.is_dir() else output.read_text(encoding='utf-8') if output.exists() else None))
    assert actual == expected


@pytest.mark.parametrize('mutation', ['truncate', 'grow', 'same-size'])
def test_input_changes_during_read_close_the_descriptor(tmp_path, monkeypatch, mutation):
    path = tmp_path / 'input.docx'
    path.write_bytes(b'abcdef')
    original = os.read
    seen = []
    def read(descriptor, count):
        seen.append(descriptor)
        before = os.stat(str(path))
        time.sleep(.01)
        with path.open('r+b') as stream:
            if mutation == 'truncate':
                stream.truncate(0)
            elif mutation == 'grow':
                stream.seek(0, 2)
                stream.write(b'growth')
            else:
                stream.write(b'CHANGED'[:before.st_size])
        if mutation == 'same-size':
            os.utime(str(path), ns=(before.st_atime_ns, before.st_mtime_ns))
        return original(descriptor, count)
    monkeypatch.setattr(os, 'read', read)
    with pytest.raises(OfficeKitError, match='truncated|changed'):
        read_document(str(path), 100, AbortController().signal)
    with pytest.raises(OSError):
        os.fstat(seen[0])


def test_cancelled_write_retires_only_its_owned_file(tmp_path):
    path = tmp_path / 'owned.txt'
    controller = AbortController()
    transaction = FileExport(str(path))
    transaction.open()
    controller.abort(RuntimeError('stopped'))
    with pytest.raises(RuntimeError, match='stopped'):
        transaction.write(b'output', controller.signal)
    transaction.close()
    assert not path.exists()


def test_successful_output_is_complete_and_closed(tmp_path):
    path = tmp_path / 'owned.txt'
    transaction = FileExport(str(path))
    transaction.open()
    transaction.write(b'complete', AbortController().signal)
    descriptor = transaction.descriptor
    transaction.close()
    assert path.read_bytes() == b'complete'
    with pytest.raises(OSError):
        os.fstat(descriptor)


@pytest.mark.parametrize('existing', [True, False])
def test_image_failure_only_removes_new_directory(tmp_path, existing):
    path = tmp_path / 'images'
    if existing:
        path.mkdir()
        (path / 'user.txt').write_bytes(b'KEEP')
    transaction = ImageExport(str(path))
    if existing:
        with pytest.raises(FileExistsError):
            transaction.open()
    else:
        transaction.open()
        (path / 'partial.png').write_bytes(b'partial')
    transaction.close()
    assert path.exists() is existing
    if existing:
        assert (path / 'user.txt').read_bytes() == b'KEEP'


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_disk_writer_before_return(tmp_path):
    started, release = threading.Event(), threading.Event()
    path = tmp_path / 'written'
    def write():
        started.set()
        assert release.wait(5)
        path.write_bytes(b'finished')
    task = asyncio.create_task(disk_call(write))
    while not started.is_set():
        await asyncio.sleep(.001)
    task.cancel()
    await asyncio.sleep(.01)
    task.cancel()
    await asyncio.sleep(.01)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert path.read_bytes() == b'finished'
