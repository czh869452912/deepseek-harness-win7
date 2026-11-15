import asyncio
from pathlib import Path
import sys
import pytest
from scripts.rc022_acp_provider_probe import observe,wait_file


@pytest.mark.asyncio
async def test_actual_acp_wire_diagnostics_permissions_and_quiescence(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert len(rows)==19
    assert all(row['value']['quiescent'] and row['listeners']==0 for row in rows.values())
    assert rows['end_turn']['value']['result']==dict(output=[dict(type='text',text='child answer')],stopReason='completed')
    assert rows['cancel']['value']['result']==dict(output=[dict(type='text',text='child answer')],stopReason='aborted')
    assert 'ACP unattended decision (policy: allow; request: execute; decision: allowed)' in rows['allow-refusal']['value']['result']['diagnostic']
    assert rows['missing-id']['value']['error']['message']=='subagent-acp: Subagent failure (provider: ACP; stage: new-session; category: protocol)'
    for row in rows.values():
        if 'result' in row['value']:
            assert row['value']['sameDisposal'] and row['value']['distinctId'] and row['value']['localAgentAbsent']


@pytest.mark.asyncio
async def test_candidate_acp_actual_activation_uses_captured_directory_and_unloads(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subprocess.local import LocalSubprocessRuntime
    from dsh.subagent.acp_candidate import CandidateSubagentAcp
    from scripts.rc022_acp_provider_probe import ROOT
    fixture=await setup(tmp_path/'host');ctx=fixture.ctx;children=[]
    await ctx.plugin(LocalSubprocessRuntime)
    original=ctx.subprocess.spawn
    def spawn(spec):
        child=original(spec);children.append(child);return child
    ctx.subprocess.spawn=spawn
    async def ensure(*_):return str(tmp_path)
    ctx.workingDirectory.ensure=ensure
    try:
        owner=await ctx.plugin(CandidateSubagentAcp,dict(command=sys.executable,args=[str(ROOT/'scripts/oracles/subagent_acp_peer.py')],
            cwd='retired config field must not select child directory',env=dict(PROBE_ECHO_CWD='1'),disposeEofGraceMs=100,disposeGraceMs=100))
        provider=fixture.service.providers['acp']
        assert dict(provider.capabilities)==dict(agentOptions=False,agentPreset=False,outputSchema=False,depthLimit=False)
        parent=(await ctx.agents.create(dict(sessionId='parent'))).agent
        receipt=await fixture.service.startActivation(dict(provider='acp',parent=parent,label='ACP task',prompt=[dict(type='text',text='task')],signal=fixture.signal,delivery='caller'))
        assert await receipt['result']==dict(output=[dict(type='text',text=str(tmp_path)+'\n'+str(tmp_path))],stopReason='completed')
        await receipt['dispose']()
        assert len(children)==1 and await children[0].wait_for_exit()
        await owner.dispose()
        assert 'acp' not in fixture.service.providers
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_unpublished_acp_start_owns_cleanup(tmp_path):
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.subprocess.local import LocalSubprocessRuntime
    from dsh.subagent.acp_candidate import CandidateAcpProvider,CandidateSubagentAcp
    from scripts.rc022_acp_provider_probe import ROOT
    from types import SimpleNamespace as NS
    ctx=Context();await ctx.plugin(LocalSubprocessRuntime)
    config=CandidateSubagentAcp.Config(dict(command=sys.executable,args=[str(ROOT/'scripts/oracles/subagent_acp_peer.py')],env=dict(PROBE_NEW_READY=str(tmp_path/'ready'),PROBE_NEW_GO=str(tmp_path/'never')),disposeEofGraceMs=30,disposeGraceMs=30))
    children=[];original=ctx.subprocess.spawn
    def spawn(spec):
        child=original(spec);children.append(child);return child
    ctx.subprocess.spawn=spawn
    try:
        pending=asyncio.create_task(CandidateAcpProvider(ctx,config).start(dict(cwd=str(tmp_path),parent=NS(),signal=AbortController().signal,prompt=[])))
        await wait_file(tmp_path/'ready');pending.cancel()
        with pytest.raises(asyncio.CancelledError):await pending
        assert len(children)==1 and await children[0].wait_for_exit()
    finally:await ctx.fiber.dispose()
