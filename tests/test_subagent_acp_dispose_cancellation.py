import asyncio
from pathlib import Path
import sys

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.subagent.acp import AcpProvider, CONFIG
from dsh.subprocess.local import LocalSubprocessRuntime
from scripts.oracles.subagent_acp_python import request, wait_file


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_cancelled_dispose_awaiter_cannot_cancel_owned_eof_flush_and_process_reap(tmp_path):
    ctx = Context()
    await ctx.plugin(LocalSubprocessRuntime)
    controller = AbortController()
    flushed = tmp_path / 'flushed'
    config = CONFIG({'command': sys.executable, 'args': [str(ROOT / 'scripts/oracles/subagent_acp_peer.py')],
        'env': {'PROBE_FLUSH': str(flushed)}, 'disposeEofGraceMs': 500, 'disposeGraceMs': 100})
    run = None
    try:
        run = await AcpProvider(ctx, config).start(request(tmp_path, controller))
        result = await run.result
        waiting = asyncio.create_task(run.dispose())
        deadline = asyncio.get_running_loop().time() + 5
        while not run.child.stdin.closed:
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0)
        assert not run.public_disposal.done()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert not run.public_disposal.cancelled()
        await asyncio.wait_for(run.dispose(), 5)
        assert flushed.read_text(encoding='utf-8') == 'flushed'
        assert await run.child.wait_for_exit()
        assert (await run.child.done).exitCode == 0
        assert not run.rpc.pending and not run.rpc.tasks and run.reader.done()
        assert not controller.signal._listeners
        assert await run.result == result == {'output': [{'type': 'text', 'text': 'child answer'}], 'stopReason': 'completed'}
    finally:
        if run is not None:
            await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_start_awaiter_reaps_unpublished_blocked_new_session_child(tmp_path):
    ctx = Context()
    await ctx.plugin(LocalSubprocessRuntime)
    service = ctx.get('subprocess')
    spawn, children = service.spawn, []
    def capture(spec):
        child = spawn(spec)
        children.append(child)
        return child
    service.spawn = capture
    ready = tmp_path / 'new-ready'
    config = CONFIG({'command': sys.executable, 'args': [str(ROOT / 'scripts/oracles/subagent_acp_peer.py')],
        'env': {'PROBE_NEW_READY': str(ready), 'PROBE_NEW_GO': str(tmp_path / 'never-go')},
        'disposeEofGraceMs': 30, 'disposeGraceMs': 30})
    try:
        starting = asyncio.create_task(AcpProvider(ctx, config).start(request(tmp_path, AbortController())))
        await wait_file(ready)
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(starting, 5)
        assert len(children) == 1 and await children[0].wait_for_exit()
        assert (await children[0].done).exitCode == 1
    finally:
        await ctx.fiber.dispose()
