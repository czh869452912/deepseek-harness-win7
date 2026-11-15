"""Pair passive buffer ordering, history replay and projection subscriptions."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_history_reads_probe import normalized
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.api.session_listeners import ListenerBuffer,EventListener,event_item
    from dsh.api.session_history_authorized import SessionHistoryReads
    from dsh.core.abort import AbortController
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];aborters=[];query_calls=[]
    def signal():
        abort=AbortController();aborters.append(abort);return abort
    async def next_value(stream):
        try:return dict(value=await stream.__anext__())
        except StopAsyncIteration:return dict(done=True)
    query=ctx.sessionQuery.observeSession
    async def observed(*args):query_calls.append(True);return await query(*args)
    ctx.sessionQuery.observeSession=observed
    try:
        abort=signal();buffer=ListenerBuffer(ctx,abort.signal);calls=[]
        def convert(value):calls.append(value);return ['n:'+str(value)]
        numbers=buffer.createInput(convert);words=buffer.createInput(lambda value:[value])
        numbers.append(2);words.prepend('first');rows.append(dict(name='lazy',calls=list(calls)))
        values=buffer.items();rows.append(dict(name='heterogeneous',values=[await next_value(values),await next_value(values)],calls=list(calls)))
        duplicate=buffer.items()
        try:await duplicate.__anext__()
        except Exception as error:rows.append(dict(name='single-consumer',code=error.code))
        numbers.append(3);rows.append(dict(name='wake',value=await next_value(values)))
        await values.aclose();closed=[];buffer.capture(lambda:closed.append('captured'));buffer.own(lambda:closed.append('owned'));numbers.append(4)
        try:buffer.createInput(lambda value:[value])
        except Exception as error:rows.append(dict(name='closed',actions=closed,message=str(error)))
        failure=RuntimeError('captured');buffer=ListenerBuffer(ctx,signal().signal)
        def fail():raise failure
        buffer.capture(fail)
        try:await buffer.items().__anext__()
        except Exception as error:rows.append(dict(name='captured-failure',same=error is failure,message=str(error)))
        buffer=ListenerBuffer(ctx,signal().signal)
        def closing(value):buffer.dispose();yield value
        buffer.createInput(closing).append(1);rows.append(dict(name='close-during-transform',value=await next_value(buffer.items())))
        history=SessionHistoryReads(ctx);abort=signal()
        stream=history.observeEvent(dict(address=dict(kind='session',sessionId='later')),abort.signal)
        rows.append(dict(name='ready-missing',value=await next_value(stream),queries=len(query_calls)))
        session=ctx.sessions.create('later',meta=dict(cwd='C:/listeners'))
        session.append('fixture/tick',dict(value=0),ignorable=True)
        rows.append(dict(name='created-after-ready',value=await next_value(stream)))
        abort.abort();rows.append(dict(name='cancel-event',value=await next_value(stream)))
        abort=signal();listener=EventListener(ctx,session.id,abort.signal)
        session.append('fixture/tick',dict(value=1),ignorable=True)
        session.append('fixture/tick',dict(value=2),ignorable=True)
        listener.setCursor(1);ctx.emit('session/created',session)
        events=listener.events();rows.append(dict(name='creation-cut',value=await next_value(events)))
        session.append('fixture/tick',dict(value=3),ignorable=True)
        rows.append(dict(name='deduplicated-suffix',value=await next_value(events)))
        await events.aclose()
        try:event_item(dict(type='event',session=session,event=session.snapshotEvents()[2]),1)
        except Exception as error:rows.append(dict(name='gap',code=error.code,message=error.message))
        external=ListenerBuffer(ctx,signal().signal);listener=EventListener(ctx,session.id,fixture.signal,external);listener.setCursor(-1);ctx.emit('session/created',session)
        values=external.items();first=await next_value(values);listener.dispose();external.dispose()
        rows.append(dict(name='external-batch-disposal',first=first,rest=await next_value(values)))
        for key,multiplier in [('ticks',1),('doubleTicks',2)]:
            await ctx.sessionProjections.register(dict(key=key,stateVersion=1,stateSchema=int,init=lambda *_:0,
                apply=lambda state,event,m=multiplier:state+m if event['type']=='fixture/tick' else state,
                wire=dict(viewSchema=int,view=lambda state:state)))
        abort=signal();changes=history.observeProjections(dict(sessionId='later'),abort.signal)
        rows.append(dict(name='projection-ready',value=await next_value(changes),queries=len(query_calls)))
        other=ctx.sessions.create('other',meta=dict(cwd='C:/listeners'));other.append('fixture/tick',dict(value=100),ignorable=True)
        session.append('fixture/tick',dict(value=4),ignorable=True)
        rows.append(dict(name='grouped-projection',value=await next_value(changes)))
        session.append('fixture/tick',dict(value=5),ignorable=True);abort.abort()
        rows.append(dict(name='cancel-discards-queued-projection',value=await next_value(changes)))
        def install(child):child.set_service('historyFixture',SessionHistoryReads(child))
        provider=await ctx.plugin(install);owned=ctx.historyFixture.observeEvent(dict(address=dict(kind='session',sessionId='later')),fixture.signal)
        await owned.__anext__();waiting=asyncio.ensure_future(next_value(owned));await provider.dispose()
        rows.append(dict(name='unload-wakes-reader',value=await waiting,queries=len(query_calls)))
        return normalized(rows)
    finally:
        for abort in aborters:abort.abort()
        await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_listeners.mts','Actual v4 Session/projection/Cordis effects and passive listeners: lazy heterogeneous buffers, single consumer, producer/transform close, readiness before existence, creation-prefix replay with cursor deduplication, gap rejection, external ownership, grouped projection changes, cancellation discarding queued frames and unload waking a reader. No query/Agent activation. Assistant reconnect state and composite follow/state streams remain separate.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_listeners.py',ROOT/'dsh/api/session_history_authorized.py',ROOT/'dsh/api/session_authorized.py'],prepare=prepare)
