import asyncio
import hashlib
import json
import threading
from pathlib import Path

import pytest

from scripts import rc022_change_inputs_probe as corpus


@pytest.mark.asyncio
async def test_original_input_corpus_and_actual_bounded_capture_ownership(tmp_path):
    corpus.prepare(tmp_path)
    rows = await corpus.observe()
    assert len(rows) == 44
    assert rows[3]['result'] == [dict(path='new', oldPath='old', added=3, deleted=4, binary=False)]
    assert rows[4]['result'][0]['path'] == 'tab\tname'
    assert rows[14]['result']['error'] == 'numstat output is not NUL-terminated'
    captures = [row['result'] for row in rows if row['kind'] == 'capture']
    assert captures[0] == dict(kind='absent')
    assert captures[3] == dict(kind='oversized')
    assert captures[2] == captures[4]
    assert captures[5]['binary'] and not captures[6]['binary'] and captures[7]['binary']
    copies = tmp_path/'files'/'native-copies'
    assert len(list(copies.iterdir())) == 5
    for file in copies.iterdir():
        assert file.name == hashlib.sha1(file.read_bytes()).hexdigest()
    assert not (copies/hashlib.sha1(b'one\ntwo').hexdigest()).exists()
    (tmp_path/'change-inputs-observations.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')


@pytest.mark.asyncio
async def test_cancelled_capture_keeps_ownership_until_actual_file_io_settles(tmp_path, monkeypatch):
    from dsh.deliverables import change_capture as module
    source = tmp_path/'source'
    source.write_bytes(b'owned data')
    entered, release = threading.Event(), threading.Event()
    original = module._capture_file
    def held(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(module, '_capture_file', held)
    pending = asyncio.create_task(module.captureFile(str(source), str(tmp_path/'copies'), 100))
    try:
        while not entered.is_set():
            await asyncio.sleep(0)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert len(list((tmp_path/'copies').iterdir())) == 1
