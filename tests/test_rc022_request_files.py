import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.core.timeout import TimeoutReason
from dsh.llm.deepseek_request_files import RequestFiles, FileResolutionFailure
from scripts import rc022_request_files_probe as corpus


def request(ensure, invalidate=None, controller=None, activity=None, timeout=1000):
    return RequestFiles(SimpleNamespace(ensureUploaded=ensure,invalidate=invalidate),
        dict(baseURL='https://example.test',headers={}),{},timeout,(controller or AbortController()).signal,activity or (lambda:None))


@pytest.mark.asyncio
async def test_stale_mapping_and_normalized_image_diagnostic_corpus(tmp_path):
    rows=await corpus.observe()
    (tmp_path/'request-files-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==2821
    assert all(row['pulses']==3 and row['other']=='provider said no' for row in rows)
    assert any(row['retry']==[True,False,False] for row in rows)
    assert any(len(row['invalidated'][0])==1 for row in rows if row['invalidated'])
    assert any(len(row['invalidated'][0])==2 for row in rows if row['invalidated'])
    assert any('Candidate images:' in row['message'] for row in rows)


@pytest.mark.asyncio
async def test_upload_deadline_wraps_failure_but_caller_abort_preserves_identity():
    signals=[]
    async def timed(version,connection,policy,signal):
        signals.append(signal)
        await signal.wait_aborted()
        signal.throw_if_aborted()
    owned=request(timed,timeout=5)
    with pytest.raises(FileResolutionFailure) as raised:
        await owned.resolve({},dict(message=1,image=1))
    assert isinstance(raised.value.cause,TimeoutReason)
    assert raised.value.cause.code=='DEEPSEEK_FILES_API_TIMEOUT' and owned.used==[]
    controller=AbortController();reason=RuntimeError('caller ended');controller.abort(reason)
    owned=request(timed,controller=controller)
    with pytest.raises(RuntimeError) as raised:
        await owned.resolve({},dict(message=1,image=1))
    assert raised.value is reason and owned.used==[]
    assert all(signal.aborted for signal in signals)


@pytest.mark.asyncio
async def test_invalidation_failure_does_not_spend_retry_and_second_rejection_still_invalidates():
    version=corpus.cases()['versions'][0];calls=[];failure=RuntimeError('index unavailable')
    async def ensure(*_):return dict(record=dict(fileId='file-1'))
    async def invalidate(records,connection):
        calls.append(records)
        if len(calls)==1:raise failure
    owned=request(ensure,invalidate)
    await owned.resolve(version,dict(message=1,image=1))
    with pytest.raises(RuntimeError) as raised:await owned.retry('file-1 expired')
    assert raised.value is failure and not owned.retried
    assert await owned.retry('file-1 expired') is True
    owned.beginAttempt()
    assert await owned.retry('file-1 expired') is False
    await owned.resolve(version,dict(message=2,image=1))
    assert await owned.retry('file-1 expired') is False
    assert len(calls)==3 and calls[-1]==[dict(variantId=version['variantId'],fileId='file-1')]


@pytest.mark.asyncio
async def test_activity_failure_is_not_an_upload_failure_or_successful_occurrence():
    async def ensure(*_):return dict(record=dict(fileId='file-1'))
    failure=RuntimeError('activity callback failed')
    def activity():raise failure
    owned=request(ensure,activity=activity)
    with pytest.raises(RuntimeError) as raised:await owned.resolve({},dict(message=1,image=1))
    assert raised.value is failure and owned.used==[]
