"""Current ACP range ownership, actual stdio peers and cancellation disposal."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.subagent.acp import CONFIG
from dsh.subagent.acp_current import CurrentAcpProvider
from dsh.subprocess.local import LocalSubprocessRuntime
from scripts.oracles.agent_loop_current_python import execute
from scripts.oracles.agent_machine_current_python import execute as machine
from scripts.oracles.session_format_python import decode
from scripts.oracles.subagent_acp_python import request, wait_file

ROOT=Path(__file__).resolve().parents[1]
CASES=json.loads((ROOT/'scripts/oracles/external_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['case'])
def test_retained_v3_acp_ownership_contract(case):
    result=(machine if case['kind']=='machine-current' else execute)(case,decode)
    assert result==case['expected']
    if case['kind']=='machine-current':
        assert result['results'][1]['outcome']=='value'
        assert result['results'][1]['value']['result']['output']==[dict(type='text',text='child answer')]


@pytest.mark.asyncio
async def test_actual_current_disposal_is_memoized_across_cancelled_awaiter(tmp_path):
    ctx=Context();await ctx.plugin(LocalSubprocessRuntime);controller=AbortController();run=None
    flushed=tmp_path/'flushed'
    config=CONFIG(dict(command=sys.executable,args=[str(ROOT/'scripts/oracles/subagent_acp_peer.py')],
                       env=dict(PROBE_FLUSH=str(flushed)),disposeEofGraceMs=500,disposeGraceMs=100))
    try:
        run=await CurrentAcpProvider(ctx,config).start(request(tmp_path,controller))
        original=await run.result
        waiting=asyncio.create_task(run.dispose())
        async def until_eof():
            while not run.child.stdin.closed:await asyncio.sleep(0)
        await asyncio.wait_for(until_eof(),3)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):await waiting
        assert not run.public_disposal.cancelled()
        await asyncio.wait_for(run.dispose(),5)
        assert flushed.read_text(encoding='utf-8')=='flushed'
        assert await run.child.wait_for_exit() and (await run.child.done).exitCode==0
        assert await run.result==original
        assert not controller.signal._listeners and run.reader.done() and not run.rpc.pending
    finally:
        if run is not None:await run.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_current_aborted_start_reaps_unpublished_real_child(tmp_path):
    ctx=Context();await ctx.plugin(LocalSubprocessRuntime);controller=AbortController()
    ready=tmp_path/'ready'
    config=CONFIG(dict(command=sys.executable,args=[str(ROOT/'scripts/oracles/subagent_acp_peer.py')],
                       env=dict(PROBE_NEW_READY=str(ready),PROBE_NEW_GO=str(tmp_path/'never-go')),disposeEofGraceMs=20,disposeGraceMs=100))
    service=ctx.get('subprocess');spawn=service.spawn;children=[]
    def capture(spec):
        child=spawn(spec);children.append(child);return child
    service.spawn=capture
    try:
        start=asyncio.create_task(CurrentAcpProvider(ctx,config).start(request(tmp_path,controller)))
        await wait_file(ready)
        controller.abort('cancel startup')
        with pytest.raises(RuntimeError,match='aborted before the ACP child started'):await asyncio.wait_for(start,5)
        assert len(children)==1 and await children[0].wait_for_exit()
        assert not controller.signal._listeners
    finally:await ctx.fiber.dispose()
