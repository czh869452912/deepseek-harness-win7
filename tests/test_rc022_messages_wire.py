import json

import pytest

from dsh.llm.deepseek_config_current import resolveAdapterOptions
from dsh.llm.deepseek_messages_replay import readReplay
from dsh.llm.deepseek_messages_serialize import serialize
from scripts import rc022_messages_wire_probe as corpus


@pytest.mark.asyncio
async def test_messages_request_and_stream_corpus_with_real_assembler(tmp_path):
    rows=await corpus.observe()
    (tmp_path/'messages-wire-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==407
    requests=[row for row in rows if row['kind']=='serialize']
    assert all(row['unchanged'] for row in requests)
    assert any(row['degraded'] for row in requests)
    assert any(row.get('code')=='INVALID_REQUEST' for row in requests)
    assert any(row.get('code')=='UNSUPPORTED_CONTENT' for row in requests)
    valid=next(row for row in rows if row['kind']=='translate' and row['index']==0)
    assert valid['assembled']['blocks']==[dict(type='text',text='initial plus')]
    assert valid['chunks'][-2]['usage']==dict(inputTokens=12,outputTokens=5,cacheReadTokens=3,totalTokens=20)
    assert valid['chunks'][-1]['type']=='finish'
    assert any(row.get('code')=='EMPTY_RESPONSE' for row in rows)
    assert any(row.get('code')=='STREAM_CLOSED' for row in rows)
    assert any(row.get('code')=='MALFORMED_RESPONSE' for row in rows)


def test_cross_model_thinking_signature_is_not_reused():
    connection=resolveAdapterOptions({})
    message=dict(role='assistant',source=dict(kind='model',provider='deepseek-official',model='old',
        replayState=dict(response=dict(kind='deepseek-messages',version=1,model='old'),blocks=[dict(type='reasoning',signature='private')])),
        content=[dict(type='reasoning',text='durable thought')])
    assert readReplay(message,'different') is None
    result=serialize(dict(model='different'),connection,[message],{},lambda _:None)
    assert result['messages'][0]['content']==[dict(type='thinking',thinking='durable thought')]
    assert message['source']['replayState']['blocks'][0]['signature']=='private'
