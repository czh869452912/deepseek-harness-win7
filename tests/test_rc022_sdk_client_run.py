import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

from dsh.core.session.json import UNDEFINED
from dsh.sdk.client import NotificationSubscription, create_process_deepseek_harness
from dsh.sdk.errors import SdkProtocolError
from dsh.sdk.run import RunActivity, validated_session_event, final_response, command_execution, run_session


@pytest.mark.parametrize('event', [None, [], {}, dict(type=1), dict(type='assistant/message',data=None),dict(type='assistant/message',data=dict(message=dict(content=[{}]))),dict(type='turn/end',data=None),dict(type='turn/end',data=dict(reason=None)),dict(type='turn/end',data=dict(reason=dict(kind='aborted'))),dict(type='turn/end',data=dict(reason=dict(kind='aborted',reason=dict(kind='unknown')))),dict(type='turn/end',data=dict(reason=dict(kind='aborted',reason=dict(kind='hook',reason=1))))])
def test_consumed_event_fields_reject_malformed_wire(event):
    with pytest.raises(SdkProtocolError):validated_session_event(event)


def test_result_validation_and_js_text_extraction():
    assert final_response([dict(type='assistant/message',data=dict(message=dict(content=[dict(type='text',text=True),dict(type='image'),dict(type='text'),dict(type='text',text=dict(x=1))])))])=='true[object Object]'
    assert command_execution(dict(commandId='c',result=dict(kind='success',text='',sourceEventSeq=0,extra=1)))==dict(commandId='c',result=dict(kind='success',text='',sourceEventSeq=0))
    for seq in [True, -1, 1.5, 10**400, None, 9007199254740992]:
        with pytest.raises(SdkProtocolError):command_execution(dict(commandId='c',result=dict(kind='success',sourceEventSeq=seq)))


@pytest.mark.asyncio
async def test_completion_before_queued_done_and_observer_failure_release_subscription():
    client=NS(subscriptions=set())
    subscription=NotificationSubscription(client,None);client.subscriptions.add(subscription)
    def note(kind,event=None,**params):return dict(method=kind,params=dict(sessionId='root',**({} if event is None else dict(event=event)),**params))
    frames=[note('session.event',dict(type='command/run',data=dict(commandId='outer'))),note('session.query.completed',commandId='outer',finishReason='completed',finalResponse='done'),note('session.event',dict(type='command/done',data=dict(commandId='nested'))),note('session.event',dict(type='command/done',data=dict(commandId='outer')))]
    async def request(*_):
        for frame in frames:subscription.push(frame)
        return dict(kind='command',execution=dict(commandId='outer',result=dict(kind='success')))
    async def start():pass
    client.request=request;client.subscribeSessionTree=lambda _:subscription
    session=NS(id='root',harness=NS(client=client,start=start))
    result=await run_session(session,'/plan')
    assert result['finalResponse']=='done' and len(result['events'])==3 and not client.subscriptions
    assert subscription.tryNext() is UNDEFINED
    subscription=NotificationSubscription(client,None);client.subscriptions.add(subscription)
    def observer(_):raise RuntimeError('observer failed')
    with pytest.raises(RuntimeError,match='observer failed'):await run_session(session,'/plan',dict(onNotification=observer))
    assert not client.subscriptions


@pytest.mark.asyncio
async def test_actual_sdk_run_prompt_command_fresh_ids_and_resume(tmp_path):
    root=Path(__file__).resolve().parents[1]
    runtime=dict(command=sys.executable,args=[str(root/'tests/fixtures/rc022_sdk_query_runtime.py'),str(tmp_path)],cwd=str(root),environment=lambda:dict(os.environ),description='SDK run integration',initializeTimeoutMs=10000,requestTimeoutMs=10000,shutdownTimeoutMs=5000,disposeEofGraceMs=5000,disposeGraceMs=1000)
    options=dict(cwd=str(tmp_path),provider='script',model='model')
    harness=create_process_deepseek_harness(runtime,options);seen=[]
    try:
        first=await harness.run('/计划 on',dict(onNotification=seen.append))
        assert first['finalResponse']=='query answer' and first['finishReason']=='completed'
        assert first['notifications']==seen
        assert all(note['method']!='session.query.completed' for note in seen)
        second=await harness.run('prompt')
        assert first['sessionId']!=second['sessionId'] and second['finalResponse']=='query answer'
        assert not harness.client.subscriptions
    finally:await harness.close()
    assert harness.client.child.poll()==0
    restored=create_process_deepseek_harness(runtime,options)
    try:
        session=await restored.resumeSession(first['sessionId'])
        assert session.id==first['sessionId']
        result=await session.run('continued')
        assert result['sessionId']==session.id and result['finalResponse']=='query answer'
    finally:await restored.close()
    assert restored.client.child.poll()==0


def test_activity_requires_matching_lifecycle_and_excludes_pre_receipt():
    activity=RunActivity('root',dict(commandId='c'));seen=[]
    assert not activity.record(dict(method='session.status',params=dict(sessionId='root',status='idle')),seen.append)
    assert not activity.record(dict(method='session.event',params=dict(sessionId='root',event=dict(type='command/run',data=dict(commandId='other')))),seen.append)
    with pytest.raises(SdkProtocolError,match='missing matching lifecycle'):activity.result(dict(finalResponse='',finishReason='error'))
    assert not seen
