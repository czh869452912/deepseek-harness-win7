import asyncio
import json

import pytest

from dsh.core.abort import AbortController
from dsh.mcp.input_required_current import pace_state_only
from dsh.mcp.negotiation_current import SdkError
from scripts import rc022_mcp_dispatch_probe as corpus


@pytest.mark.asyncio
async def test_real_sdk_dispatch_corpus_preserves_modern_errors_retries_and_manual_mode(tmp_path):
    corpus.prepare(tmp_path)
    try:
        rows = await corpus.observe()
        assert len(rows) == 29
        exceeded = rows[1]['result']['thrown']
        assert exceeded['code'] == 'INPUT_REQUIRED_ROUNDS_EXCEEDED'
        assert exceeded['data']['rounds'] == 10
        retries = [packet for packet in rows[1]['packets'] if packet['method'] == 'tools/list']
        assert len(retries) == 11
        assert all(packet['params']['requestState'] == 'opaque' for packet in retries[1:])
        assert rows[11]['result']['listing']['tools'] == []
        assert rows[13]['result']['listing']['tools'] == []
        assert rows[23]['result']['thrown']['code'] == 'CAPABILITY_NOT_SUPPORTED'
        assert rows[26]['result']['listing'] == dict(resultType='input_required', inputRequests={}, requestState='opaque')
        assert rows[27]['result']['thrown']['code'] == 'UNSUPPORTED_RESULT_TYPE'
        assert rows[28]['result']['thrown']['data']['rounds'] == 2
        (tmp_path/'dispatch-observations.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    finally:
        corpus.driver.stop_peer()


@pytest.mark.asyncio
@pytest.mark.parametrize('task_cancel', [False, True])
async def test_state_only_pacing_releases_abort_listener_and_owned_timer(monkeypatch, task_cancel):
    signal = AbortController()
    loop = asyncio.get_running_loop()
    handles = []
    original = loop.call_later
    def record(*args, **kwargs):
        handle = original(*args, **kwargs)
        handles.append(handle)
        return handle
    monkeypatch.setattr(loop, 'call_later', record)
    waiting = asyncio.create_task(pace_state_only(signal.signal))
    await asyncio.sleep(0)
    assert len(handles) == 1
    if task_cancel:
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
    else:
        reason = SdkError('REQUEST_TIMEOUT', 'controlled')
        signal.abort(reason)
        with pytest.raises(SdkError) as raised:
            await waiting
        assert raised.value is reason
    assert handles[0].cancelled()
    assert not signal.signal._listeners
