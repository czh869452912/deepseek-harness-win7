import asyncio
from types import SimpleNamespace

import pytest

from dsh.api.terminal_controller_authorized import AuthorizedTerminalController,title
from dsh.core.abort import AbortController
from dsh.typert.remote import RemoteError
from scripts.rc022_terminal_controller_probe import fixture

REQUEST=dict(id='one',cols=20,rows=4)


async def settled(predicate):
    async def wait():
        while not predicate():await asyncio.sleep(.001)
    await asyncio.wait_for(wait(),3)


def signal():return AbortController().signal


@pytest.mark.asyncio
async def test_actual_controller_paired_allocation_and_sandbox_history_contract():
    from scripts.rc022_terminal_controller_probe import observe
    rows=await observe()
    assert next(row for row in rows if row['name']=='idempotent')['extra']['same']
    race=next(row for row in rows if row['name']=='close-during-allocation')
    assert race['terminations']==[1] and race['roster']==[]
    assert race['extra'][:2]==['Terminal was closed in this Session']*2
    launch=next(row for row in rows if row['name']=='agent-launch')['launch']
    assert launch['argv']==['confined','sh','-i']
    assert launch['env']['HISTFILE']=='/tmp/dsh-agent-history-fixed-agent'


def test_config_omitted_shell_explicit_args_and_title_utf16_limits():
    defaults=AuthorizedTerminalController.Config({})
    assert 'shell' not in defaults and defaults['maxAgentTerminals']==4
    assert AuthorizedTerminalController.Config(dict(shell=dict(path='sh',name='Shell')))['shell']['args']==[]
    assert title('\ufeff named \u3000')=='named'
    assert title('😀'*60)=='😀'*60
    for value in ('\ufeff','😀'*61,' '+'a'*120):
        with pytest.raises(ValueError,match='1–120'):title(value)


@pytest.mark.asyncio
async def test_duplicate_creation_ignores_later_signal_and_pending_reserves_capacity():
    ctx,controller,agent,provider,handles,calls=await fixture()
    try:
        provider.gate=asyncio.Event();first=asyncio.ensure_future(controller.create(agent,REQUEST,signal()))
        await settled(lambda:len(handles)==1)
        cancelled=AbortController();cancelled.abort(RuntimeError('duplicate caller cancelled'))
        duplicate=asyncio.ensure_future(controller.create(agent,REQUEST,cancelled.signal))
        other=asyncio.ensure_future(controller.create(agent,dict(REQUEST,id='two'),signal()))
        await settled(lambda:len(handles)==2)
        with pytest.raises(RemoteError) as failure:await controller.create(agent,dict(REQUEST,id='three'),signal())
        assert failure.value.code=='terminal/limit-reached'
        provider.gate.set();a,b,_=await asyncio.gather(first,duplicate,other)
        assert a is b and len(handles)==2 and not controller.owners[agent.id].pending
    finally:
        if provider.gate is not None:provider.gate.set()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_screen_creation_retains_failed_cleanup_and_reservation_until_retry():
    ctx,controller,agent,provider,handles,calls=await fixture()
    original=ctx.terminalScreens.open;abort=AbortController()
    try:
        async def opening(options):
            screen=await original(options);handles[0].failures=1;abort.abort(RuntimeError('cancelled after screen'));return screen
        ctx.terminalScreens.open=opening
        with pytest.raises(Exception,match='Terminal allocation cleanup failed'):await controller.create(agent,REQUEST,abort.signal)
        owner=controller.owners[agent.id]
        assert list(owner.allocations)==['one'] and not owner.terminals and not owner.pending
        assert controller.list(agent.id)[0]['state']=='failed'
        with pytest.raises(RemoteError,match='closed'):await controller.create(agent,REQUEST,signal())
        assert len(ctx.terminalScreens.engines)==1
        await controller.close(agent,'one')
        assert not owner.allocations and not ctx.terminalScreens.engines and not ctx.jsRuntime._workers
        assert handles[0].terminated==2
    finally:ctx.terminalScreens.open=original;await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_host_disposal_joins_inflight_screen_creation_and_releases_actual_worker():
    ctx,controller,agent,provider,handles,calls=await fixture()
    original=ctx.terminalScreens.open;entered=asyncio.Event();gate=asyncio.Event();creating=disposing=None
    try:
        async def opening(options):
            screen=await original(options);entered.set();await gate.wait();return screen
        ctx.terminalScreens.open=opening
        creating=asyncio.ensure_future(controller.create(agent,REQUEST,signal()))
        await asyncio.wait_for(entered.wait(),3)
        disposing=asyncio.ensure_future(controller.dispose());await asyncio.sleep(0)
        assert not disposing.done();gate.set()
        with pytest.raises(RuntimeError,match='disposed'):await creating
        await disposing
        assert not controller.owners and handles[0].terminated==1
        assert not ctx.terminalScreens.engines and not ctx.jsRuntime._workers
    finally:
        gate.set();await asyncio.gather(*(task for task in (creating,disposing) if task is not None),return_exceptions=True)
        ctx.terminalScreens.open=original;await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_roster_watchers_coalesce_changes_cancel_independently_and_close_on_dispose():
    ctx,controller,agent,provider,handles,calls=await fixture()
    streams=[]
    try:
        first_abort=AbortController();first=controller.watch(agent.id,first_abort.signal);second=controller.watch(agent.id,signal());streams=[first,second]
        assert await first.__anext__()==[] and await second.__anext__()==[]
        first_wait=asyncio.ensure_future(first.__anext__());second_wait=asyncio.ensure_future(second.__anext__())
        await asyncio.sleep(0);await controller.create(agent,REQUEST,signal())
        assert (await first_wait)[0]['id']=='one' and (await second_wait)[0]['id']=='one'
        first_wait=asyncio.ensure_future(first.__anext__());await asyncio.sleep(0);first_abort.abort()
        with pytest.raises(StopAsyncIteration):await first_wait
        assert len(controller.rosters[agent.id])==1
        second_wait=asyncio.ensure_future(second.__anext__());await asyncio.sleep(0)
        controller.rename(agent,'one',' first ');controller.rename(agent,'one','final')
        assert (await second_wait)[0]['title']=='final'
        second_wait=asyncio.ensure_future(second.__anext__());await asyncio.sleep(0);await controller.dispose()
        with pytest.raises(StopAsyncIteration):await second_wait
        assert not controller.rosters
    finally:
        for stream in streams:await stream.aclose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_agent_fiber_owns_process_and_other_session_cannot_access_it():
    ctx,controller,agent,provider,handles,calls=await fixture()
    captured=[]
    try:
        def plugin(child):captured.append(SimpleNamespace(id='child',ctx=child,session=SimpleNamespace(id='child',header={})))
        fork=await ctx.plugin(plugin);child=captured[0]
        await controller.create(child,REQUEST,signal())
        assert controller.list(agent.id)==[]
        with pytest.raises(RemoteError,match='no longer exists'):await controller.readScreen(agent,'one',dict(offset=0,count=10,maxBytes=1000))
        await fork.dispose()
        assert handles[0].terminated==1 and not controller.list(child.id) and not controller.owners
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_session_and_host_cleanup_keeps_owner_and_can_retry():
    ctx,controller,agent,provider,handles,calls=await fixture()
    try:
        await controller.create(agent,REQUEST,signal());handles[0].failures=1
        owner=controller.owners[agent.id]
        with pytest.raises(Exception,match='Session terminal cleanup failed'):await controller.disposeOwner(agent.id,owner)
        assert owner.cleanup is None and 'one' in owner.terminals and owner.lifetime.signal.aborted
        await controller.disposeOwner(agent.id,owner)
        assert not controller.owners and handles[0].terminated==2 and not ctx.jsRuntime._workers
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_screen_read_race_classifies_released_screen_and_missing_sandbox_prevents_spawn():
    ctx,controller,agent,provider,handles,calls=await fixture()
    try:
        with pytest.raises(RuntimeError,match='require a sandbox provider'):
            await controller.openForAgent(agent,dict(title='agent',cols=20,rows=4,policy=dict(mode='read-only'),preferredShells=[]),signal())
        assert not handles
        await controller.create(agent,REQUEST,signal());terminal=controller.terminal(agent,'one')
        gate=asyncio.Event();terminal.enqueue(gate.wait)
        read=asyncio.ensure_future(controller.readScreen(agent,'one',dict(offset=0,count=10,maxBytes=1000)))
        await asyncio.sleep(0);terminal.screenDisposed=True;gate.set()
        with pytest.raises(RemoteError,match='closed in this Session'):await read
    finally:await ctx.fiber.dispose()
