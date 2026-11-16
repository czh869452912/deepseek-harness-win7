import asyncio
import threading

import pytest

from dsh.core.abort import AbortController
from dsh.web.deepseek_api_transport import resolveCredential
from dsh.web.web_service import WebError
from scripts.rc022_web_api_transport_probe import observe, cases


@pytest.mark.asyncio
async def test_real_http_credential_order_rejection_and_cancellation_corpus():
    before = {thread.ident for thread in threading.enumerate()}
    rows = await observe()
    assert len(rows) == len(cases()) == 52
    assert all(row['listeners'] == 0 and len(row['hits']) <= 1 for row in rows)
    for case, row in zip(cases(), rows):
        for hit in row['hits']:
            if 'x-dsh-auth-token' in hit['headers']:
                assert 'authorization' not in hit['headers'] and 'x-api-key' not in hit['headers']
            else:
                assert hit['headers']['authorization'] == 'Bearer api-key'
        if case['mode'] == 'unauthorized-removal-error' and case['sources'] == ['account']:
            assert row['events'].count('reject:account-token') == 1
            assert 'sign in to DeepSeek again' in row['result']['message']
        if case['mode'] == 'unauthorized-body-abort' and case['sources'] == ['account']:
            assert row['events'].count('reject:account-token') == 1
            assert row['result']['code'] == 'WEB_ABORTED'
        if case['mode'] in ('record-error', 'wait-error', 'pre-abort', 'resolve-abort', 'resolve-reject-late'):
            assert not row['hits']
    assert not [thread for thread in threading.enumerate() if thread.ident not in before and
                thread.name in ('web-api-transport-probe', 'dsh-model-reader', 'dsh-http-cancellation')]


@pytest.mark.asyncio
async def test_aborted_credential_resolver_remains_observed_without_cancelling_owner():
    loop = asyncio.get_running_loop(); previous = loop.get_exception_handler(); failures = []
    loop.set_exception_handler(lambda _, context: failures.append(context))
    controller = AbortController(); pending = loop.create_future(); entered = asyncio.Event()
    async def resolve():
        entered.set()
        return await pending
    try:
        task = asyncio.create_task(resolveCredential(resolve, controller.signal))
        await entered.wait(); controller.abort(RuntimeError('private-cancel'))
        with pytest.raises(WebError) as caught:
            await task
        assert caught.value.code == 'WEB_ABORTED'
        assert not pending.done() and not controller.signal._listeners
        pending.set_exception(RuntimeError('late-private-failure'))
        for _ in range(4): await asyncio.sleep(0)
        assert not failures
    finally:
        loop.set_exception_handler(previous)
