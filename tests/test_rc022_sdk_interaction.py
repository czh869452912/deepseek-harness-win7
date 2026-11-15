import asyncio
import io
import json
import os
from pathlib import Path
import sys

import pytest

from dsh.core.abort import AbortController
from dsh.sdk.transport import JsonRpcLineTransport
from scripts import rc022_sdk_interaction_probe as probe


@pytest.mark.asyncio
async def test_sdk_question_and_approval_ownership_contract(tmp_path):
    probe.WORKSPACE=tmp_path
    rows={row['name']:row for row in await probe.observe()}
    assert len(rows)==29
    assert rows['answer']['result']['value']==dict(answers=[dict(id='q',selected=['A'],custom='text')])
    assert rows['dismissed']['result']['code']=='ASK_CANCELLED'
    assert rows['duplicate']['result']['code']=='BAD_ANSWER'
    assert rows['request-abort']['code']=='ASK_ABORTED'
    assert len(rows['question-shutdown']['notifications'])==2
    assert rows['question-shutdown']['error']=='SDK server is shutting down'
    assert rows['approval-descendant']['result']['value']=='allowed-once'
    assert rows['approval-unowned']['result']['value']==rows['approval-stale']['result']['value']=='fallback'


@pytest.mark.asyncio
@pytest.mark.parametrize('reason,rendered',[(None,'null'),(False,'false'),(0,'0'),('stop','stop'),(dict(value=1),'[object Object]')])
async def test_transport_abort_is_immediate_and_removes_signal_listener(reason,rendered):
    controller=AbortController();transport=JsonRpcLineTransport(None,io.StringIO())
    pending=asyncio.create_task(transport.request('ask',{},controller.signal));await asyncio.sleep(0)
    assert len(transport.pending)==1
    controller.abort(reason);assert not transport.pending
    with pytest.raises(RuntimeError,match='JSON-RPC request aborted:') as error:await pending
    assert str(error.value)=='JSON-RPC request aborted: '+rendered
    assert not controller.signal._listeners


@pytest.mark.asyncio
async def test_transport_preserves_abort_exception_identity_and_preabort_admission():
    controller=AbortController();reason=ValueError('original');controller.abort(reason)
    output=io.StringIO();transport=JsonRpcLineTransport(None,output)
    with pytest.raises(ValueError) as caught:await transport.request('ask',{},controller.signal)
    assert caught.value is reason and not transport.pending and output.getvalue()==''
    controller=AbortController();pending=asyncio.create_task(transport.request('ask',{},controller.signal));await asyncio.sleep(0);controller.abort(reason)
    with pytest.raises(ValueError) as caught:await pending
    assert caught.value is reason and not controller.signal._listeners


@pytest.mark.asyncio
async def test_real_sdk_stdio_question_tool_and_client_callback(tmp_path):
    from dsh.sdk.client import create_process_deepseek_harness
    root=Path(__file__).resolve().parents[1];seen=[]
    async def answer(request,options):
        seen.append(request)
        assert not options['signal'].aborted
        return dict(answers=[dict(id='format',selected=['CSV'],custom='header')])
    runtime=dict(command=sys.executable,args=[str(root/'tests/fixtures/rc022_sdk_interaction_runtime.py'),str(tmp_path)],cwd=str(root),environment=lambda:dict(os.environ),description='actual SDK question',initializeTimeoutMs=10000,requestTimeoutMs=10000,shutdownTimeoutMs=5000,disposeEofGraceMs=5000,disposeGraceMs=1000)
    harness=create_process_deepseek_harness(runtime,dict(cwd=str(tmp_path),provider='script',model='model',onUserQuestion=answer))
    notifications=harness.client.subscribe()
    try:
        await harness.start()
        await harness.client.prompt('root',[dict(type='text',text='ask')])
        assert await harness.client.request('session/wait',dict(sessionId='root'))=={}
        assert len(seen)==1 and seen[0]['sessionId']=='root'
        assert seen[0]['questions'][0]['id']=='format'
        results=[item['params']['event']['data']['message'] for item in notifications.queue if item['method']=='session.event' and item['params']['event']['type']=='tool/result']
        assert len(results)==1 and results[0]['isError'] is False
        assert json.loads(results[0]['content'][0]['text'])==dict(answers=[dict(id='format',selected=['CSV'],custom='header')])
    finally:notifications.close();await harness.close()
    client=harness.client
    assert client.child.poll()==0 and not client.transport.pending and not client.user_questions
    assert all(stream.closed for stream in (client.child.stdin,client.child.stdout,client.child.stderr))
