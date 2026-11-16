import asyncio
from contextlib import asynccontextmanager
import json
import threading

import pytest

from dsh.core.abort import AbortController
from dsh.llm import deepseek_messages_adapter as module
from dsh.llm.llm_service import LlmError
from scripts import rc022_messages_adapter_probe as corpus


def request():
    return dict(provider='deepseek-official', model='m', messages=[dict(role='user', source=dict(kind='user'), content=[dict(type='text', text='hi')])])


def dependencies(configuration, **extra):
    async def auth(connection): return dict(headers={'x-api-key': 'secret'})
    async def extensions(request):
        async def accept(): pass
        return dict(fields={}, accept=accept)
    result = dict(options=lambda: configuration, resolveAuth=auth, resolveUserId=lambda: 'user', prepareExtensions=extensions)
    result.update(extra); return result


@pytest.mark.asyncio
async def test_actual_messages_adapter_http_and_durable_files(tmp_path):
    before = {thread.ident for thread in threading.enumerate()}
    rows = await corpus.observe(tmp_path/'files')
    (tmp_path/'messages-adapter-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == 33
    real = next(row for row in rows if row['mode'] == 'real-upload')
    assert len([hit for hit in real['hits'] if hit['path'].endswith('/files')]) == 1
    stale = next(row for row in rows if row['mode'] == 'real-stale')
    assert len(stale['hits']) == 4 and stale['disk']['records'][0]['fileId'] == 'file-2'
    early = next(row for row in rows if row['mode'] == 'early-close')
    assert [chunk['type'] for chunk in early['result']['chunks']] == ['block-start']
    assert 'error' not in next(row for row in rows if row['mode'] == 'slow-consumer')['result']
    assert next(row for row in rows if row['mode'] == 'broken-chunk')['result']['error']['message'] == 'DeepSeek Messages transport failed'
    for _ in range(100):
        active = [thread for thread in threading.enumerate() if thread.ident not in before
                  and thread.name in ('dsh-model-reader', 'dsh-http-cancellation', 'messages-adapter-probe')]
        if not active: break
        await asyncio.sleep(.002)
    assert not active


@pytest.mark.asyncio
async def test_prepared_call_captures_connection_and_direct_call_resolves_current_options(monkeypatch):
    first = corpus.config(); first['baseURL'] = 'https://first.test/anthropic'
    second = corpus.config(); second['baseURL'] = 'https://second.test/anthropic'
    holder = dict(options=first); seen = []; admitted = []
    @asynccontextmanager
    async def http(url, headers, payload, signal):
        seen.append(url)
        async def chunks():
            yield ''.join('event: '+event['type']+'\ndata: '+json.dumps(event)+'\n\n' for event in corpus.events()).encode('utf-8')
        yield dict(status=200, headers={}, hasBody=True), chunks()
    monkeypatch.setattr(module, 'requestMessages', http)
    adapter = module.DeepSeekMessagesAdapter(dependencies(first, options=lambda: holder['options'],
        admit=lambda connection, model: admitted.append(connection['baseURL'])))
    try:
        prepared = await adapter.prepareCall('deepseek-official', 'm')
        holder['options'] = second
        assert (await adapter.listModels('deepseek-official')) == []
        assert (await adapter.resolveModel('deepseek-official', 'm'))['id'] == 'm'
        assert [chunk async for chunk in prepared['stream'](request())][-1]['type'] == 'finish'
        assert [chunk async for chunk in adapter.stream(request())][-1]['type'] == 'finish'
        assert seen == ['https://first.test/anthropic/v1/messages', 'https://second.test/anthropic/v1/messages']
        assert admitted == ['https://first.test/anthropic', 'https://second.test/anthropic']
    finally: await adapter.close()


@pytest.mark.asyncio
async def test_timeout_can_end_a_hanging_extension_and_join_native_demand():
    options = corpus.config(); options['streamIdleTimeoutMs'] = 20
    entered = asyncio.Event(); closed = asyncio.Event(); caller = AbortController()
    async def extensions(request):
        entered.set()
        try: await asyncio.Event().wait()
        finally: closed.set()
    adapter = module.DeepSeekMessagesAdapter(dependencies(options, prepareExtensions=extensions))
    stream = adapter.stream(dict(request(), signal=caller.signal))
    try:
        with pytest.raises(LlmError) as caught: await asyncio.wait_for(stream.__anext__(), 1)
        assert caught.value.code == 'TIMEOUT' and caught.value.message == 'DeepSeek Messages stream idle timeout'
        assert entered.is_set() and closed.is_set() and not caller.signal._listeners
    finally:
        await stream.aclose(); await adapter.close()
