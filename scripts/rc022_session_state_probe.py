"""Pair passive execution state, coalescing and non-destructive waits."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from scripts.rc022_inbox_readers_probe import message
    from dsh.api.session_history_authorized import SessionHistoryController
    from dsh.api.session_state_authorized import SessionStateController,StateListener
    from dsh.core.abort import AbortController
    from dsh.core.session.plugin_records import appendPluginRecord
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];pending=[];streams=[];aborters=[];tasks=[]
    ctx.set_service('typertGateway',NS(getPendingRemoteEvents=lambda:pending))
    history=SessionHistoryController(ctx);state=SessionStateController(ctx,history);signal=fixture.signal
    def add(event,identity='state'):pending.append(dict(event=event,agentId=identity))
    def result(value):return dict(reason=value['reason'],active=value['state']['active'],running=value['state']['running'],pendingInput=value['state']['pendingInput'],outputRecords=len(value['output']['records']),truncated=value['output']['truncated'])
    try:
        handle=await ctx.agents.create(dict(sessionId='state',meta=dict(cwd='C:/state'),agentOptions=dict(provider='script',model='model')));agent=handle.agent;request=dict(sessionId='state')
        rows.append(dict(name='live-idle',value=await state.state(request,signal)))
        queued=message('queued');steering=message('steer');steering['source']['rpcId']='rpc';context=message('context');context['source']=dict(kind='user-approval')
        agent.inbox.append('next-turn',queued);agent.inbox.append('next-step',steering);agent.inbox.append('next-step',context)
        rows.append(dict(name='queue',value=(await state.state(request,signal))['queue']))
        add('approval/request');add('user-questions/request');add('custom/request');add('approval/request');add('ignored','other')
        rows.append(dict(name='pending',value=(await state.state(request,signal))['pendingInput']))
        rows.append(dict(name='input-before-idle',value=result(await state.wait(request,signal))))
        pending.clear();agent.inbox.clear()
        rows.append(dict(name='active-idle-wait',value=result(await state.wait(request,signal))))
        abort=AbortController();aborters.append(abort);states=state.observeState(request,abort.signal);streams.append(states);await states.__anext__()
        appendPluginRecord(agent.session,'plugin:fixture/tick',dict(n=1));appendPluginRecord(agent.session,'plugin:fixture/tick',dict(n=2))
        value=await states.__anext__();rows.append(dict(name='coalesced',cursor=value['cursor'],expected=agent.session.seq-1))
        read=asyncio.ensure_future(states.__anext__());tasks.append(read);await asyncio.sleep(0);abort.abort()
        try:await read
        except StopAsyncIteration:rows.append(dict(name='observe-cancel',ended=True))
        await states.aclose()
        agent.followup(message('run'))
        async def started():
            while history.streamsListener.streams.get(agent.id) is None or history.streamsListener.streams[agent.id].snapshot().get('activeAttempt',{}).get('nextIndex',0)<2:
                await asyncio.sleep(0)
        await asyncio.wait_for(started(),5)
        rows.append(dict(name='running-timeout',value=result(await state.wait(dict(request,timeoutMs=25),signal)),stillRunning=agent.status=='running',callerAborted=signal.aborted))
        cancel=AbortController();aborters.append(cancel);task=asyncio.ensure_future(state.wait(request,cancel.signal));tasks.append(task);await asyncio.sleep(0);primary=RuntimeError('caller cancelled');cancel.abort(primary)
        try:await task
        except Exception as error:rows.append(dict(name='caller-cancel',same=error is primary,stillRunning=agent.status=='running'))
        task=asyncio.ensure_future(state.wait(dict(request,timeoutMs=2500),signal));tasks.append(task);await asyncio.sleep(0);add('user-questions/request')
        rows.append(dict(name='pending-periodic',value=result(await task),stillRunning=agent.status=='running'))
        pending.clear();agent.cancel();await asyncio.wait_for(agent.whenIdle(),5)
        rows.append(dict(name='after-execution',value=result(await state.wait(request,signal))))
        await handle.dispose()
        value=await state.state(request,signal);rows.append(dict(name='cold-state',value=value,agentAbsent=ctx.agents.get('state') is None))
        rows.append(dict(name='cold-wait',value=result(await state.wait(request,signal))))
        for bound in (dict(afterSeq=-2),dict(afterSeq=-0.0),dict(maxMessages=0),dict(timeoutMs=0),dict(timeoutMs=2147483648),dict(timeoutMs=1.5)):
            try:await state.wait(dict(request,**bound),signal)
            except Exception as error:rows.append(dict(name='bounds',bound=bound,code=error.code))
        try:await state.state(dict(sessionId='missing'),signal)
        except Exception as error:rows.append(dict(name='missing',code=error.code))
        return json.loads(json.dumps(rows))
    finally:
        for abort in aborters:abort.abort()
        await asyncio.gather(*tasks,return_exceptions=True)
        for stream in streams:await stream.aclose()
        await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_state.mts','Actual Session/Agent/Inbox/JSONL/query/history state: passive cold and live reads, queue identity, classified pending inputs, coalesced changes, observation cancellation, actual running-Agent deadline/caller cancellation/periodic pending input, quiescence and bounded output. Pending Gateway event inventory is controlled; full controller initialization remains separate.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_state_authorized.py',ROOT/'dsh/api/session_authorized.py'],prepare=prepare)
