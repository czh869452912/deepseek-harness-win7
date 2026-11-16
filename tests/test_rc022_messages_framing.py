import json

import pytest

from dsh.llm.deepseek_messages_sse import parseSse
from dsh.llm.deepseek_messages_translate import translate
from scripts import rc022_messages_framing_probe as corpus


@pytest.mark.asyncio
async def test_sse_frames_and_provider_error_precedence_corpus(tmp_path):
    rows=await corpus.observe()
    (tmp_path/'messages-framing-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==1352
    sse=[row for row in rows if row['kind']=='sse']
    assert any(row.get('pulses',0)>len(row['values']) for row in sse)
    assert any(row.get('code')=='AUTH' for row in sse)
    assert any(row.get('code')=='MALFORMED_RESPONSE' for row in sse)
    errors=[row for row in rows if row['kind']=='error' and 'failure' in row]
    assert {row['failure']['code'] for row in errors}>={'AUTH','QUOTA','RATE_LIMIT','CONTEXT_WINDOW_EXCEEDED','INVALID_REQUEST','SERVER','HTTP_404'}
    assert any(row['failure'].get('providerRetryAfterMs')==250 for row in errors)
    assert any(row['failure'].get('requestId')=='primary' for row in errors)


@pytest.mark.asyncio
async def test_sse_early_close_and_bad_frame_close_owned_byte_iterator():
    closed=[]
    async def body(payload):
        try:
            yield payload
            yield b'data: {"type":"ping"}\n\n'
        finally: closed.append(True)
    parsed=parseSse(body(b'data: {"type":"ping"}\n\n'),lambda:None)
    assert (await parsed.__anext__())==dict(type='ping')
    await parsed.aclose()
    assert closed==[True]
    with pytest.raises(Exception) as raised:
        async for _ in parseSse(body(b'data: bad\n\n'),lambda:None): pass
    assert raised.value.code=='MALFORMED_RESPONSE' and closed==[True,True]


@pytest.mark.asyncio
async def test_translator_finish_and_consumer_close_own_upstream_events():
    closed=[]
    async def events():
        try:
            yield dict(type='message_start',message=dict(usage={}))
            yield dict(type='content_block_start',index=0,content_block=dict(type='text',text='hi'))
            yield dict(type='content_block_stop',index=0)
            yield dict(type='message_delta',delta=dict(stop_reason='end_turn'))
            yield dict(type='message_stop')
            raise AssertionError('translator read past settlement')
        finally: closed.append(True)
    chunks=[chunk async for chunk in translate(events(),'m')]
    assert chunks[-1]['type']=='finish' and closed==[True]
    stream=translate(events(),'m')
    assert (await stream.__anext__())['type']=='block-start'
    await stream.aclose()
    assert closed==[True,True]
