import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

from dsh.cordis import Context
from dsh.code_runtime.confined_ptc import ConfinedPythonPtcRuntime
from dsh.core.abort import AbortController
from dsh.sandbox.local import LocalSandboxProvider
from dsh.sandbox.sandbox_policy import SandboxPolicyService
from dsh.sandbox.vocabulary import SandboxUnavailableError


async def setup(workspace, mode='read-only', provider=None):
    ctx = Context()
    if provider is None:
        await ctx.plugin(LocalSandboxProvider)
    else:
        ctx.set_service('sandbox', provider)
    await ctx.plugin(SandboxPolicyService, dict(mode=mode, workspaceRoot=str(workspace)))
    fiber = await ctx.plugin(ConfinedPythonPtcRuntime, dict(timeoutMs=5000))
    return ctx, ctx.get('ptcRuntime'), fiber


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows ACL backend')
@pytest.mark.asyncio
async def test_actual_policy_denials_and_full_access_are_reported_without_fallback(tmp_path):
    workspace = tmp_path/'workspace'
    workspace.mkdir()
    outside = tmp_path/'outside'
    ctx, runtime, unused = await setup(workspace)
    try:
        assert runtime.sandboxMode == 'read-only' and 'follows this execution' in runtime.executionInstructions
        code = "from pathlib import Path\nPath('inside').write_text('yes',encoding='utf-8')\nreturn 42"
        result = await runtime.run(runtime.resolve(dict(program=code, bindings=[])))
        assert result['error']['kind'] == 'exception', result
        assert result['sandbox'] == dict(mode='read-only', enforcement='partial', denied=True)
        assert not (workspace/'inside').exists()
        policy = dict(mode='workspace-write', workspaceRoot=str(workspace), sessionId='owned')
        result = await runtime.run(runtime.resolve(dict(program=code, bindings=[], sandboxPolicy=policy)))
        assert result == dict(logs=[], value=42, sandbox=dict(mode='workspace-write', enforcement='partial', denied=False))
        assert (workspace/'inside').read_text(encoding='utf-8') == 'yes'
        code = "from pathlib import Path\nPath(%s).write_text('outside',encoding='utf-8')\nreturn 42" % json.dumps(str(outside))
        result = await runtime.run(runtime.resolve(dict(program=code, bindings=[], sandboxPolicy=policy)))
        assert result['sandbox']['denied'] and not outside.exists()
        policy['mode'] = 'danger-full-access'
        result = await runtime.run(runtime.resolve(dict(program=code, bindings=[], sandboxPolicy=policy)))
        assert result == dict(logs=[], value=42, sandbox=dict(mode='danger-full-access', denied=False))
        assert outside.read_text(encoding='utf-8') == 'outside'
        assert not runtime.live and not runtime.runs and not runtime.processes.processes
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unavailable_provider_never_launches_a_program(tmp_path, monkeypatch):
    entered = []
    def confine(argv, policy):
        entered.append(policy['mode'])
        raise SandboxUnavailableError(policy['mode'], 'backend missing')
    ctx, runtime, unused = await setup(tmp_path, provider=SimpleNamespace(confine=confine))
    def fail(*args, **kwargs):
        raise AssertionError('must not allocate a process')
    monkeypatch.setattr('dsh.code_runtime.process.ProcessOwner', fail)
    try:
        result = await runtime.run(runtime.resolve(dict(program='return 42', bindings=[])))
        assert result['error']['kind'] == 'sandbox-unavailable'
        assert result['sandbox'] == dict(mode='read-only', denied=False)
        assert entered == ['read-only']
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_runner_startup_and_executable_failures_are_infrastructure_errors(tmp_path):
    executable = getattr(sys, '_base_executable', sys.executable)
    providers = [SimpleNamespace(confine=lambda argv,policy:dict(argv=[executable,'-c',
                    "import sys;sys.stderr.write('runner: startup denied\\n');sys.exit(127)"],
                    enforcement='partial', denialSignatures=['denied'],
                    runnerFailureRules=[dict(allowedExitCodes=[127],fatalSignatures=['runner:'])])),
                 SimpleNamespace(confine=lambda argv,policy:dict(argv=[str(tmp_path/'missing.exe')],
                    enforcement='partial',denialSignatures=[],runnerFailureRules=[]))]
    for provider in providers:
        ctx, runtime, unused = await setup(tmp_path, provider=provider)
        try:
            result = await runtime.run(runtime.resolve(dict(program='return 42', bindings=[])))
            assert result['error']['kind'] == 'sandbox-unavailable', result
            assert result['sandbox'] == dict(mode='read-only',enforcement='partial',denied=False)
        finally:
            await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_only_selected_denial_dialect_is_classified(tmp_path):
    for signature, denied in [('EPERM',False), ('EACCES',True)]:
        # Controlled wrapper seam fixture, not evidence of OS confinement.
        provider = SimpleNamespace(confine=lambda argv,policy:dict(argv=argv,
            enforcement='partial', denialSignatures=[signature], runnerFailureRules=[]))
        ctx, runtime, unused = await setup(tmp_path, provider=provider)
        try:
            result = await runtime.run(runtime.resolve(dict(program="raise PermissionError('EACCES file denied')", bindings=[])))
            assert result['error']['kind'] == 'exception' and result['sandbox']['denied'] == denied
        finally:
            await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_deadline_and_abort_cover_pending_confinement_without_spawning(tmp_path, monkeypatch):
    entered, stopped = asyncio.Event(), asyncio.Event()
    async def confine(argv, policy):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    provider = SimpleNamespace(confine=confine)
    ctx, runtime, unused = await setup(tmp_path, provider=provider)
    def fail(*args, **kwargs):
        raise AssertionError('must not allocate a process')
    monkeypatch.setattr('dsh.code_runtime.process.ProcessOwner', fail)
    try:
        result = await runtime.run(runtime.resolve(dict(program='return 42',bindings=[],timeoutMs=50)))
        assert result['error']['kind'] == 'timeout' and stopped.is_set()
        entered.clear()
        stopped.clear()
        controller = AbortController()
        task = asyncio.create_task(runtime.run(runtime.resolve(dict(program='return 42',bindings=[],signal=controller.signal))))
        await entered.wait()
        controller.abort('caller canceled')
        result = await task
        assert result['error']['kind'] == 'abort' and stopped.is_set()
        assert not runtime.live and not runtime.runs
    finally:
        await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows ACL backend')
@pytest.mark.asyncio
async def test_committed_v4_session_policy_cancels_worker_without_cancelling_nested_tool(tmp_path):
    from dsh.core.session.current_session import CurrentSessionStore
    ctx, runtime, fiber = await setup(tmp_path, mode='workspace-write')
    store = CurrentSessionStore(ctx, format_version=4)
    session = store.create('policy-ptc')
    entered, release, settled = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def slow(args):
        entered.set()
        await release.wait()
        settled.set()
        return None
    try:
        spec = runtime.resolve(dict(program='return await tools.slow({})',
            bindings=[dict({'global':'tools'},functions=dict(slow=slow))],
            sandboxPolicy=ctx.get('sandboxPolicy').resolve(dict(session=session))))
        task = asyncio.create_task(runtime.run(spec))
        await asyncio.wait_for(entered.wait(), 5)
        session.append('sandbox/mode',dict(mode='read-only'))
        result = await asyncio.wait_for(task, 5)
        assert result['error']['kind'] == 'abort' and not settled.is_set()
        assert ctx.get('sandboxPolicy').resolve(dict(session=session))['mode'] == 'read-only'
        await runtime.processes.wait(session.id)
        release.set()
        await settled.wait()
        await fiber.dispose()
        assert not runtime.live and not runtime.runs and not runtime.processes.processes
    finally:
        release.set()
        await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows ACL backend')
@pytest.mark.asyncio
async def test_selected_ptc_executor_uses_real_confined_worker_and_session_events(tmp_path):
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.core.tool_executor_ptc import PtcToolExecutorPlugin
    ctx, runtime, unused = await setup(tmp_path, mode='workspace-write')
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(CurrentToolsPlugin)
    store = CurrentSessionStore(ctx, format_version=4)
    session = store.create('executor-ptc')
    agent = SimpleNamespace(ctx=ctx, session=session)
    ctx.set_service('workingDirectory', SimpleNamespace(ensure=lambda agent,signal:str(tmp_path)))
    await ctx.plugin(PtcToolExecutorPlugin)
    ctx.tools.register(dict(name='double',description='Double a value',parameters=dict(type='object',
        properties=dict(n=dict(type='number')),required=['n']),execute=lambda args,execution:args['n']*2,
        output=dict(schema=dict(type='number'),render=lambda args,value:[dict(type='text',text=str(value))])))
    try:
        batch = await ctx.tools.execute(dict(agent=agent,signal=AbortController().signal,
            calls=[dict(type='tool-call',id='outer',name='run_code',arguments=json.dumps(dict(
                code="from pathlib import Path\nPath('created').write_text('yes',encoding='utf-8')\nreturn await tools.double({'n':21})",
                description='Write an owned file and calculate a value')))],log=dict(turn=1,step=1)))
        result = batch['results'][0]['result']
        assert not result.is_error, result.error
        assert result.value == dict(logs=[],result=42,sandbox=dict(mode='workspace-write',enforcement='partial',denied=False))
        assert (tmp_path/'created').read_text(encoding='utf-8') == 'yes'
        types = [event['type'] for event in session.events]
        assert types == ['tool/call','tool/ptc-dispatch-start','tool/ptc-dispatch','tool/result']
        session.append('sandbox/mode',dict(mode='read-only'))
        arguments = dict(code="from pathlib import Path\nPath('created').write_text('updated',encoding='utf-8')\nreturn 42",
                         description='Update the owned file')
        async def execute(call_id, args):
            batch = await ctx.tools.execute(dict(agent=agent,signal=AbortController().signal,
                calls=[dict(type='tool-call',id=call_id,name='run_code',arguments=json.dumps(args))]))
            return batch['results'][0]['result']
        denied = await execute('denied',arguments)
        assert denied.is_error and denied.error['info']['code'] == 'CODE_RUN_FAILED'
        assert 'operation denied' in denied.error['message']
        approvals = []
        def approve(request):
            approvals.append(request)
            return 'allowed-once'
        ctx.set_service('approval',SimpleNamespace(request=approve))
        allowed = await execute('approved',dict(arguments,sandbox_permissions='workspace-write',
            justification='Update the file after the observed read-only denial.'))
        assert not allowed.is_error and allowed.value['result'] == 42
        assert approvals[0]['agent'] is agent and approvals[0]['callId'] == 'approved'
        assert approvals[0]['toolName'] == 'run_code'
        assert ctx.get('sandboxPolicy').resolve(dict(session=session))['mode'] == 'read-only'
        assert (tmp_path/'created').read_text(encoding='utf-8') == 'updated'
        assert (await execute('standing',arguments)).is_error
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unloading_provider_cancels_pending_confinement_and_releases_admission(tmp_path):
    entered, stopped = asyncio.Event(), asyncio.Event()
    async def confine(argv, policy):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    ctx, runtime, fiber = await setup(tmp_path,provider=SimpleNamespace(confine=confine))
    try:
        pending = asyncio.create_task(runtime.run(runtime.resolve(dict(program='return 42',bindings=[]))))
        await entered.wait()
        await asyncio.wait_for(fiber.dispose(),3)
        result = await pending
        assert result['error']['kind'] == 'abort' and stopped.is_set()
        assert not runtime.live and not runtime.runs and not runtime.processes.processes
        assert ctx.get('ptcRuntime') is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('confined',[True,False])
async def test_failed_cleanup_cannot_publish_a_successful_result(tmp_path,monkeypatch,confined):
    from dsh.code_runtime.process import ProcessOwner
    original = ProcessOwner.close
    failures = []
    def close(owner):
        original(owner)
        if not failures:
            failures.append(1)
            raise RuntimeError('process observation failed')
    monkeypatch.setattr(ProcessOwner,'close',close)
    if confined:
        ctx,runtime,unused = await setup(tmp_path,mode='danger-full-access')
    else:
        from dsh.code_runtime.ptc import PythonPtcRuntime
        ctx = Context()
        await ctx.plugin(PythonPtcRuntime)
        runtime = ctx.get('ptcRuntime')
    try:
        result = await runtime.run(runtime.resolve(dict(program="print('observed')\nreturn 42",bindings=[])))
        assert result['error'] == dict(kind='worker-exit',message='managed process cleanup failed: process observation failed')
        assert result['logs'] == ['observed'] and 'value' not in result
        assert not runtime.runs
        if confined:
            assert not runtime.live
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_confined_provider_requires_resolved_authority_before_allocation(tmp_path):
    ctx, runtime, unused = await setup(tmp_path)
    try:
        for policy in (None, {}, dict(mode='unknown',workspaceRoot=str(tmp_path)),
                       dict(mode='read-only',workspaceRoot='relative')):
            with pytest.raises(ValueError, match='sandbox policy'):
                await runtime.run(dict(program='return 42',bindings=[],cwd=str(tmp_path),timeoutMs=5000,sandboxPolicy=policy))
        with pytest.raises(ValueError, match='cwd must be absolute'):
            runtime.resolve(dict(program='',bindings=[],cwd='relative'))
        result = await runtime.run(runtime.resolve(dict(program='return 42',bindings=[],
            sandboxPolicy=dict(mode='danger-full-access',workspaceRoot=str(tmp_path)))))
        assert result['value'] == 42
    finally:
        await ctx.fiber.dispose()
