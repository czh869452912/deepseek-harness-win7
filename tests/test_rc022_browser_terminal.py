import asyncio
from contextlib import asynccontextmanager

import pytest

from dsh.api.terminal_authorized import BrowserTerminal,AgentTerminalError
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.javascript.runtime import JavaScriptRuntime
from dsh.terminal.screen_runtime import TerminalScreenRuntime
from dsh.typert.uplink_inbox import UplinkInbox
from dsh.typert.invocation import UplinkDecoder
from scripts.rc022_browser_terminal_probe import Channel

LIMITS=dict(maxInputBytes=12,maxCols=200,maxRows=100)
PAGE=dict(offset=0,count=100,maxBytes=1000)


@asynccontextmanager
async def fixture(maximum=100000):
    ctx=Context();terminal=None
    class Handle:
        pid=123
        def __init__(self):
            self.output=Channel();self.done=asyncio.get_running_loop().create_future()
            self.writes=[];self.terminations=0;self.finish_gate=None;self.write_error=None
        async def write(self,data):
            if self.write_error is not None:raise self.write_error
            self.writes.append(data)
        async def resize(self,cols,rows):pass
        async def inspectActivity(self):return dict(state='unknown',revision=0)
        async def inspectForeground(self):return None
        async def signalForeground(self,signal):return 123
        async def terminate(self):
            self.terminations+=1
            if self.finish_gate is not None:await self.finish_gate.wait()
            if not self.done.done():self.done.set_result(dict(exitCode=0,signal=None))
            await self.output.aclose()
    handle=Handle()
    try:
        await ctx.plugin(JavaScriptRuntime);await ctx.plugin(TerminalScreenRuntime)
        screen=await ctx.terminalScreens.open(dict(cols=20,rows=4,scrollback=6))
        terminal=BrowserTerminal(handle,dict(id='test',state='running',control='agent',cols=20,rows=4),screen,maximum)
        yield terminal,handle,ctx
    finally:
        if handle.finish_gate is not None:handle.finish_gate.set()
        if terminal is not None:await terminal.dispose()
        await ctx.fiber.dispose()


async def settled(predicate):
    async def wait():
        while not predicate():await asyncio.sleep(.001)
    await asyncio.wait_for(wait(),3)


@pytest.mark.asyncio
async def test_paired_full_owner_scenarios_actual_xterm_and_interruptible_uplink():
    from scripts.rc022_browser_terminal_probe import observe
    rows=await observe()
    assert rows[-1]==dict(name='disposed',engines=0,workers=0)
    takeover=next(row for row in rows if row['name']=='takeover')
    assert all(takeover[key]['code']=='user-control' for key in ('write','signal','close'))
    exclusive=next(row for row in rows if row['name']=='exclusive')
    assert exclusive['writes']==['echo agent\r','person']
    assert any(frame.get('refusal')=='read-only' for frame in exclusive['views'][0]['frames'])
    closed=next(row for row in rows if row['name']=='closed')
    assert closed['terminated']==1 and closed['released']==['release']


@pytest.mark.asyncio
async def test_actual_gateway_decoder_return_interrupts_pending_read_without_terminating():
    async with fixture() as (terminal,handle,ctx):
        abort=AbortController();inbox=UplinkInbox(1000,'terminal/attach',lambda _:None)
        decoder=UplinkDecoder(inbox,dict(mode='src-json'),'terminal/attach',abort.signal,abort.abort)
        stream=terminal.attach(decoder,LIMITS,abort.signal)
        assert (await stream.__anext__())['writable']
        reading=asyncio.ensure_future(stream.__anext__());await asyncio.sleep(0)
        abort.abort()
        with pytest.raises(StopAsyncIteration):await asyncio.wait_for(reading,2)
        await stream.aclose()
        assert decoder.closed and inbox.closed and not decoder.reads and not decoder.interrupted
        assert handle.terminations==0 and not terminal.followers and terminal.controller is None


@pytest.mark.asyncio
async def test_done_blocks_input_before_tail_output_and_published_exit_and_flushes_utf8():
    async with fixture() as (terminal,handle,ctx):
        handle.done.set_result(dict(exitCode=9,signal=None))
        await settled(lambda:terminal.exited)
        assert terminal.info['state']=='running'
        with pytest.raises(AgentTerminalError) as caught:await terminal.agentWrite('late')
        assert caught.value.code=='not-running' and not handle.writes
        handle.output.push(b'last\xe4');await handle.output.aclose();await terminal.drained
        assert terminal.info['state']=='exited' and terminal.info['exitCode']==9
        assert terminal.readScreen(PAGE)['text']=='last\ufffd'


@pytest.mark.asyncio
async def test_cancelling_cleanup_awaiter_does_not_cancel_process_or_screen_cleanup():
    async with fixture() as (terminal,handle,ctx):
        handle.finish_gate=asyncio.Event();closing=terminal.close()
        async def join():await closing
        task=asyncio.ensure_future(join());await settled(lambda:handle.terminations==1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert terminal.close() is closing and not terminal.screenReleased
        handle.finish_gate.set();await closing
        assert terminal.screenReleased and not ctx.terminalScreens.engines and not ctx.jsRuntime._workers


@pytest.mark.asyncio
async def test_cancel_first_attachment_read_rolls_back_queued_baseline_and_input_control():
    async with fixture() as (terminal,handle,ctx):
        gate=asyncio.Event();terminal.enqueue(gate.wait)
        stream=terminal.attach(Channel(),LIMITS,AbortController().signal)
        reading=asyncio.ensure_future(stream.__anext__());await asyncio.sleep(0);reading.cancel();gate.set()
        with pytest.raises(asyncio.CancelledError):await asyncio.wait_for(reading,2)
        assert not terminal.followers and terminal.controller is None and handle.terminations==0
        await terminal.agentWrite('still running');assert handle.writes==['still running']


@pytest.mark.asyncio
async def test_overflow_isolated_to_follower_reconnect_recovers_screen():
    async with fixture(30) as (terminal,handle,ctx):
        abort=AbortController();stream=terminal.attach(Channel(),LIMITS,abort.signal)
        await stream.__anext__();handle.output.push(b'full output');await settled(lambda:terminal.sequence==1)
        with pytest.raises(RuntimeError,match='exceeded its buffer'):await stream.__anext__()
        assert not terminal.followers and handle.terminations==0
        second=terminal.attach(Channel(),LIMITS,abort.signal)
        assert 'full output' in (await second.__anext__())['screen']
        await second.aclose()


@pytest.mark.asyncio
async def test_provider_failure_after_early_done_becomes_not_running_ack():
    async with fixture() as (terminal,handle,ctx):
        abort=AbortController();channel=Channel();stream=terminal.attach(channel,LIMITS,abort.signal)
        await stream.__anext__();handle.done.set_result(dict(exitCode=0,signal=None))
        await settled(lambda:terminal.exited)
        channel.push(dict(type='write',sequence=1,data='late'))
        assert await stream.__anext__()==dict(type='ack',sequence=1,refusal='not-running')
        await stream.aclose();assert not handle.writes


@pytest.mark.asyncio
async def test_changed_caller_task_cancel_removes_waiters_and_already_newer_ignores_abort():
    async with fixture() as (terminal,handle,ctx):
        abort=AbortController();task=asyncio.ensure_future(terminal.changed(terminal.revision,abort.signal))
        await asyncio.sleep(0);assert len(terminal.waiters)==1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert not terminal.waiters
        terminal.rename('new');abort.abort(RuntimeError('late abort'))
        assert await terminal.changed(0,abort.signal)==terminal.revision


@pytest.mark.asyncio
async def test_monitor_holds_live_process_and_dispose_joins_release_and_owner_callbacks():
    async with fixture() as (terminal,handle,ctx):
        calls=[]
        terminal.monitor(dict(unattendedTimeoutMs=0,activityPollMs=5,cleanupRetryMs=5),lambda:calls.append('closing'),lambda:calls.append('closed'),lambda _:calls.append('failed'))
        hold=terminal.retain(AbortController().signal);assert await hold.__anext__()==dict(type='retained')
        await terminal.dispose()
        with pytest.raises(StopAsyncIteration):await hold.__anext__()
        assert calls==['closing','closed'] and handle.terminations==1
        assert not terminal.retention.holders and terminal.retention.timer is None
