import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from dsh.mcp.deadline_current import with_deadline
from dsh.mcp.diagnostic_current import describe_error,McpLocalError
from dsh.mcp.generation_current import McpGeneration
from dsh.mcp.stdio_client import StdioMcpClient
from scripts.rc022_mcp_generation_probe import observe
from scripts.oracles.rc022_mcp_negotiation_peer import alive


def test_generation_lifecycle_corpus():
    rows=asyncio.run(observe())
    assert len(rows)==8
    assert all(row['sameClose'] and row['resultIdentity'] and row['afterPending']==0 for row in rows)
    local=next(row for row in rows if row['mode']=='local-unsettled')
    assert local['result']==dict(closeConfirmed=True,cleanupError='Error: MCP cleanup did not settle')
    assert local['beforeRelease']['pending']==1
    assert next(row for row in rows if row['mode']=='no-close-event')['result']['closeConfirmed'] is False


def test_cancelling_cleanup_awaiter_task_keeps_shared_cleanup_alive():
    async def run():
        generation=McpGeneration(NS(transport=None),1000,describe_error)
        held=asyncio.get_running_loop().create_future();entered=asyncio.Event()
        async def work(signal):entered.set();await held;return 'finished'
        caller=generation.run(work);await entered.wait()
        cleanup=generation.close();awaiter=asyncio.ensure_future(cleanup)
        await asyncio.sleep(0);awaiter.cancel()
        with pytest.raises(asyncio.CancelledError):await awaiter
        assert not cleanup.task.cancelled() and not cleanup.task.done()
        with pytest.raises(McpLocalError,match='MCP connection closed'):await caller
        assert len(generation._pending)==1
        held.set_result(None)
        assert await generation.close()==dict(closeConfirmed=True)
        assert generation.close() is cleanup and not generation._pending
    asyncio.run(run())


def test_cancelled_run_caller_does_not_cancel_actual_work_or_lose_late_failure():
    async def run():
        generation=McpGeneration(NS(transport=None),1000,describe_error)
        held=asyncio.get_running_loop().create_future();entered=asyncio.Event();errors=[]
        asyncio.get_running_loop().set_exception_handler(lambda loop,context:errors.append(context))
        async def work(signal):entered.set();await held;raise RuntimeError('late failure')
        caller=generation.run(work);await entered.wait();caller.cancel()
        with pytest.raises(asyncio.CancelledError):await caller
        assert len(generation._pending)==1
        cleanup=generation.close();held.set_result(None)
        assert await cleanup==dict(closeConfirmed=True)
        assert not generation._pending and not errors
    asyncio.run(run())


def test_deadline_checks_elapsed_time_when_event_loop_timers_fire_early():
    async def run():
        loop=asyncio.get_running_loop();resolution=loop._clock_resolution
        async def work():
            for _ in range(3):await asyncio.sleep(0)
            return 'finished'
        try:
            loop._clock_resolution=1
            assert await with_deadline(work(),500,'premature deadline')=='finished'
        finally:loop._clock_resolution=resolution
    asyncio.run(run())


@pytest.mark.asyncio
async def test_raw_stdio_start_has_no_handshake_and_close_reaps_process(tmp_path):
    peer=Path(__file__).resolve().parents[1]/'scripts/oracles/rc022_mcp_negotiation_peer.py'
    log=tmp_path/'peer.jsonl';transport=StdioMcpClient(sys.executable,[str(peer),str(log),'legacy'])
    try:
        await transport.start()
        async def started():
            while not log.exists():await asyncio.sleep(.005)
        await asyncio.wait_for(started(),5)
        assert transport.server_capabilities is None and not transport._pending
        assert not any(json.loads(line)['event']=='packet' for line in log.read_text(encoding='utf-8').splitlines())
    finally:await transport.close()
    starts=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines() if json.loads(line)['event']=='start']
    assert len(starts)==1 and not alive(starts[0]['pid'])
    (tmp_path/'generation-raw-start-observations.json').write_text(json.dumps(dict(events=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()],closed=True),indent=2),encoding='utf-8')
