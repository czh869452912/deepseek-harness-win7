import copy
import json
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.llm.deepseek_config_current import resolveAdapterOptions
from dsh.llm.deepseek_messages_images import prepareImages, inlineImages, prepareFileIds
from dsh.llm.llm_service import LlmError
from scripts import rc022_messages_images_probe as corpus


@pytest.mark.asyncio
async def test_geometry_pricing_and_budget_corpus(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'messages-images-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows) == 1179
    geometry = [row for row in rows if row['kind']=='geometry']
    assert all(0 < row['tokens'] <= 1024 and max(row['target']['width'],row['target']['height']) <= 4096 for row in geometry)
    preparation = [row for row in rows if row['kind']=='preparation']
    assert all(row['unchanged'] for row in preparation)
    assert any(row.get('code')=='IMAGE_OFFLOAD_REQUIRED' for row in preparation)
    assert any(row.get('inlineError',{}).get('offloadImages',0)>0 for row in preparation)
    assert any(len(row['occurrences'])>len(row['calls']) for row in preparation)


@pytest.mark.asyncio
async def test_offloaded_only_history_needs_no_attachment_service_or_vision_model():
    ref=corpus.cases()['pricing'][0]['images'][0]['attachment']
    history=[dict(role='user',content=[dict(type='image',attachment=ref,offloaded=True)])]
    before=copy.deepcopy(history)
    prepared=await prepareImages(history,resolveAdapterOptions({}),'unknown',None,lambda _:None,AbortController().signal)
    assert prepared['versions']=={} and prepared['messages'][0]['content'][0]['type']=='text'
    assert 'attach it again' in prepared['messages'][0]['content'][0]['text']
    assert history==before


@pytest.mark.asyncio
async def test_inline_budget_failure_does_not_rewrite_the_prepared_or_durable_history():
    ref=corpus.cases()['pricing'][0]['images'][0]['attachment']
    history=[dict(role='user',content=[dict(type='image',attachment=ref)])]
    before=copy.deepcopy(history)
    calls=[]
    async def read(ref,target,signal):
        return dict(attachment=ref,bytes=3,width=target['width'],height=target['height'])
    async def resolve(version,location):
        calls.append(location)
        return 'file-one'
    config=resolveAdapterOptions(dict(models=[dict(id='m',inputModalities=['image'])],maxRequestFilesBytes=3,imageOffloadByteQuantum=1,
        maxInlineRequestImageBytes=3,inlineImageOffloadByteQuantum=1))
    prepared=await prepareImages(history,config,'m',SimpleNamespace(readImageRequest=read),lambda _:None,AbortController().signal)
    assert await prepareFileIds(prepared['messages'],prepared['versions'],SimpleNamespace(resolve=resolve))=={ref['attachmentId']:'file-one'}
    assert calls==[dict(message=1,image=1)]
    with pytest.raises(LlmError) as raised:
        inlineImages(prepared['messages'],prepared['versions'],config)
    assert raised.value.code=='IMAGE_OFFLOAD_REQUIRED' and raised.value.failure['offloadImages']==1
    assert prepared['messages']==before and history==before


@pytest.mark.asyncio
async def test_attachment_cancellation_reason_propagates_before_later_versions():
    images=corpus.cases()['pricing'][0]['images'][:3]
    controller=AbortController();reason=RuntimeError('request disposed');calls=[]
    async def read(ref,target,signal):
        calls.append(ref['attachmentId'])
        controller.abort(reason)
        signal.throw_if_aborted()
    with pytest.raises(RuntimeError) as raised:
        await prepareImages([dict(role='user',content=images)],
            resolveAdapterOptions(dict(models=[dict(id='m',inputModalities=['image'])])),
            'm',SimpleNamespace(readImageRequest=read),lambda _:None,controller.signal)
    assert raised.value is reason and calls==[images[0]['attachment']['attachmentId']]
