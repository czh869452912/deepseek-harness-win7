import asyncio
import contextlib
import json
import threading
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.llm import deepseek_files_current as files
from scripts import rc022_files_http_probe as corpus


@pytest.mark.asyncio
async def test_actual_messages_files_http_corpus(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'files-http-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == 66
    assert rows[0]['result']['value']['createdAt'] == 1794873601
    assert sum(len(row['hits']) for row in rows) == 63  # Three invalid expiries never leave the process.
    assert len(rows[41]['hits'][0]['fields']) == 3
    assert rows[-2]['result']['error']['code'] == 'TRANSPORT'
    assert rows[-2]['hits'][0]['path'].endswith('/file-a')


@pytest.mark.asyncio
async def test_preaborted_request_preserves_reason_and_skips_http(monkeypatch):
    controller = AbortController(); reason = RuntimeError('caller cancelled'); controller.abort(reason)
    def unexpected(*args, **kwargs): raise AssertionError('HTTP should not start')
    monkeypatch.setattr(files, 'open_stream', unexpected)
    with pytest.raises(RuntimeError) as raised:
        await files.DeepSeekFilesClient('https://example.test/anthropic', {}).retrieve('a', controller.signal)
    assert raised.value is reason
    assert not controller.signal._listeners


@pytest.mark.asyncio
async def test_task_cancellation_joins_owned_reader_and_detaches_signal(monkeypatch):
    entered = threading.Event(); closed = threading.Event(); controller = AbortController()
    @contextlib.contextmanager
    def stream(request, signal, **kwargs):
        def chunks():
            entered.set()
            while not signal.aborted:
                closed.wait(.002)
            signal.throw_if_aborted()
            yield b''
        try: yield SimpleNamespace(status=200, headers={}), chunks()
        finally: closed.set()
    monkeypatch.setattr(files, 'open_stream', stream)
    task = asyncio.create_task(files.DeepSeekFilesClient('https://example.test', {}).retrieve('a', controller.signal))
    try:
        for _ in range(500):
            if entered.is_set(): break
            await asyncio.sleep(.002)
        assert entered.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task, 2)
        assert closed.is_set()
        assert not controller.signal._listeners
    finally:
        if not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
