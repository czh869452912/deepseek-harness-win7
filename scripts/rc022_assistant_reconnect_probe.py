"""Pair Assistant reconnect baselines and connection-local arrival cuts."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.api.session_history_authorized import SessionHistoryController
    from dsh.api.session_listeners import ListenerBuffer
    from dsh.core.abort import AbortController
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];abort=AbortController()
    try:
        history=SessionHistoryController(ctx);streams=history.streamsListener
        session=ctx.sessions.create('target',meta=dict(cwd='C:/reconnect'))
        class Agent:pass
        agent=Agent();agent.id=session.id;agent.session=session
        queue=ListenerBuffer(ctx,abort.signal);listener=streams.bind(session.id,abort.signal,queue)
        def emit(frame):ctx.emit('agent/assistant-stream',dict(agent=agent,frame=frame))
        start=dict(type='start',attemptId='attempt',revision=1,turn=1,step=1)
        rows.append(dict(name='empty',value=listener.snapshot()))
        emit(start);opening=listener.snapshot();listener.setOrdinalCut(opening['ordinal'])
        rows.append(dict(name='opening',value=opening,stable=listener.snapshot()['baseline'] is opening['baseline']))
        chunk=dict(type='chunk',attemptId='attempt',revision=2,index=0,time=4,chunk=dict(type='text-delta',index=0,text='partial'))
        emit(chunk);rows.append(dict(name='chunk-baseline',value=listener.snapshot(),old=opening))
        second_queue=ListenerBuffer(ctx,abort.signal);second=streams.bind(session.id,abort.signal,second_queue)
        rows.append(dict(name='second-connection',value=second.snapshot(),shared=second.snapshot()['baseline'] is listener.snapshot()['baseline']))
        end=dict(type='end',attemptId='attempt',revision=3,index=1,outcome=dict(kind='abandoned'))
        emit(end);values=queue.items();second_values=second_queue.items()
        rows.append(dict(name='uncovered-frames',values=[await values.__anext__(),await values.__anext__()],second=await second_values.__anext__()))
        ctx.emit('agent/disposed',dict(agent=agent));rows.append(dict(name='disposed-baseline',value=listener.snapshot()))
        session.append('fixture/tick',dict(value=1),ignorable=True)
        emit(dict(start,attemptId='new'))
        rows.append(dict(name='new-lifecycle',baseline=listener.snapshot(),wire=await values.__anext__()))
        emit(dict(chunk,attemptId='new',revision=3,index=9))
        rows.append(dict(name='gap-clears-attempt',value=listener.snapshot()))
        second.dispose();marker=second_queue.createInput(lambda value:[dict(marker=value)]);marker.append('still-open')
        rows.append(dict(name='unbound-queue',value=await second_values.__anext__(),closed=second_queue.closed))
        listener.dispose();abort.abort()
        ended=[]
        for source in (values,second_values):
            try:await source.__anext__();ended.append(False)
            except StopAsyncIteration:ended.append(True)
        rows.append(dict(name='cancelled',ended=ended))
        return json.loads(json.dumps(rows))
    finally:abort.abort();await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_assistant_reconnect.mts','Actual Cordis/Session and Assistant accumulator/buffer providers with controlled trusted Agent notifications: shared identity-stable reconnect baselines, per-connection arrival cuts, retained prior snapshots, durable start cursor, lifecycle reset, gap refusal and external queue ownership. Actual generation and composite Web follow remain separate.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_assistant_listeners.py',ROOT/'dsh/api/session_assistant_stream_current.py',ROOT/'dsh/api/session_history_authorized.py',ROOT/'dsh/api/session_authorized.py'],prepare=prepare)
