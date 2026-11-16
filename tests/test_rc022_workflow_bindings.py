import asyncio
import json
import sys

import pytest

from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from scripts.oracles.generate_agent_machine_current_cases import response
from scripts.rc022_candidate_fixture import setup


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='Actual private Win7 JavaScript worker')
async def test_loader_workflow_tool_actual_guest_v4_child_and_worker_release(tmp_path):
    extra = [('sandbox-policy', dict(mode='workspace-write', workspaceRoot=str(tmp_path))),
        ('subagent', {}), ('subagent-spawn-in-process', {}), ('workflow-ptc', dict(maxTotalAgents=2)), ('tool-workflow', {})]
    ctx = await setup(tmp_path, extra=extra, script=[response('actual child')]); lease = None
    javascript = ctx.jsRuntime
    try:
        lease = await ctx.agents.create(dict(sessionId='parent', agentOptions=dict(provider='script', model='m')))
        result = await asyncio.wait_for(ctx.tools.execute(ToolExecutionInput('workflow-call', 'workflow',
            dict(script="return await agent('task')", meta=dict(name='candidate', description='Actual candidate child')),
            agent=lease.agent, signal=NEVER_ABORTED)), 15)
        assert not result.is_error, result.error
        assert result.value['agentsStarted'] == 1 and result.value['result'] == 'actual child'
        children = [event for event in lease.agent.session.events if event['type'] == 'tool-workflow/agent-start']
        assert len(children) == 1, lease.agent.session.events
        child_id = children[0]['data']['childId']
        assert ctx.agents.get(child_id) is None
        stored = await ctx.sessionQuery.readSession(child_id)
        assert stored['session'].version == 4
        assert any(event['type'] == 'working-directory/change' and event['data']['cwd'] == str(tmp_path) for event in stored['events'])
        assert not javascript._workers
        (tmp_path/'workflow-binding-observations.json').write_text(json.dumps(dict(result=result.value, childId=child_id, childVersion=stored['session'].version, childEvents=stored['events']), indent=2), encoding='utf-8')
    finally:
        if lease is not None: await lease.dispose()
        await ctx.fiber.dispose()
    assert not javascript._workers


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != 'win32', reason='Actual policy-owned Windows Python PTC process')
async def test_loader_explicit_python_ptc_overlay_actual_tool_dispatch_and_release(tmp_path):
    extra = [('sandbox-policy', dict(mode='danger-full-access', workspaceRoot=str(tmp_path))), ('sandbox-local', {}),
        ('ptc-runtime-python', dict(timeoutMs=5000)), ('tool-executor-ptc', {})]
    def prepare(ctx):
        ctx.inject(['tools'], lambda child: child.tools.register(dict(name='double', description='Double a value',
            parameters=dict(type='object', properties=dict(n=dict(type='number')), required=['n']),
            execute=lambda args, execution: args['n']*2,
            output=dict(schema=dict(type='number'), render=lambda args, value:[dict(type='text', text=str(value))]))))
    ctx = await setup(tmp_path, extra=extra, prepare=prepare, omit=('tool-executor-native',)); lease = None; runtime = ctx.ptcRuntime
    try:
        assert runtime.language == 'python' and runtime.sandboxMode == 'danger-full-access'
        lease = await ctx.agents.create(dict(sessionId='parent', agentOptions=dict(provider='script', model='m')))
        batch = await asyncio.wait_for(ctx.tools.execute(dict(agent=lease.agent, signal=NEVER_ABORTED,
            calls=[dict(type='tool-call', id='outer', name='run_code', arguments=json.dumps(dict(code="return await tools.double({'n':21})", description='Calculate through an actual process')))],
            log=dict(turn=1, step=1))), 15)
        result = batch['results'][0]['result']
        assert not result.is_error, result.error
        assert result.value['result'] == 42 and not runtime.live
        types = [event['type'] for event in lease.agent.session.events]
        assert types.count('tool/ptc-dispatch-start') == types.count('tool/ptc-dispatch') == 1
        (tmp_path/'ptc-binding-observations.json').write_text(json.dumps(dict(result=result.value, eventTypes=types), indent=2), encoding='utf-8')
    finally:
        if lease is not None: await lease.dispose()
        await ctx.fiber.dispose()
    assert not runtime.live
