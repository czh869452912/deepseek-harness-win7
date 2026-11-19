"""Pair actual file-policy PTC programs and committed Session invalidation."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE = ROOT


def project(result):
    return dict(error=result['error']['kind'], sandbox=result['sandbox']) if 'error' in result else dict(
        value=result.get('value'), sandbox=result['sandbox'])


async def observe():
    from dsh.cordis import Context
    from dsh.code_runtime.confined_ptc import ConfinedPythonPtcRuntime
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.sandbox.local import LocalSandboxProvider
    from dsh.sandbox.sandbox_policy import SandboxPolicyService
    from dsh.core.abort import AbortController
    ctx = Context()
    await ctx.plugin(LocalSandboxProvider)
    await ctx.plugin(SandboxPolicyService, dict(mode='read-only',workspaceRoot=str(WORKSPACE)))
    await ctx.plugin(ConfinedPythonPtcRuntime, dict(timeoutMs=5000))
    runtime = ctx.get('ptcRuntime')
    store = CurrentSessionStore(ctx,format_version=4)
    rows = []
    try:
        bindings = []
        spec = runtime.resolve(dict(program='',bindings=bindings))
        rows.append(dict(name='defaults',mode=spec['sandboxPolicy']['mode'],cwd=spec['cwd']==str(WORKSPACE),
                         timeout=spec['timeoutMs'],bindingIdentity=spec['bindings'] is bindings))
        spec = runtime.resolve(dict(program='',bindings=bindings,timeoutMs=None,sandboxPolicy=None))
        rows.append(dict(name='null-defaults',mode=spec['sandboxPolicy']['mode'],timeout=spec['timeoutMs']))
        for name, mode, program in [('readonly','read-only',"from pathlib import Path\nPath('inside').write_text('yes',encoding='utf-8')\nreturn 42"),
                ('workspace','workspace-write',"from pathlib import Path\nPath('inside').write_text('yes',encoding='utf-8')\nreturn 42"),
                ('outside','workspace-write',"from pathlib import Path\nPath('../outside').write_text('yes',encoding='utf-8')\nreturn 42"),
                ('full','danger-full-access','return 42'),
                ('environment','workspace-write','import os\nreturn dict(os.environ)'),
                ('timeout','workspace-write','while True:\n    pass')]:
            spec = runtime.resolve(dict(program=program,bindings=[],timeoutMs=200 if name=='timeout' else 5000,
                sandboxPolicy=dict(mode=mode,workspaceRoot=str(WORKSPACE))))
            rows.append(dict(name=name,result=project(await runtime.run(spec))))
        session = store.create('policy-live')
        entered, release, settled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def slow(args):
            entered.set()
            await release.wait()
            settled.set()
            return None
        pending = asyncio.create_task(runtime.run(runtime.resolve(dict(program='return await tools.slow({})',
            bindings=[dict({'global':'tools'},functions=dict(slow=slow))],
            sandboxPolicy=ctx.get('sandboxPolicy').resolve(dict(session=session,mode='workspace-write'))))))
        await asyncio.wait_for(entered.wait(), 5)
        session.append('sandbox/mode',dict(mode='workspace-write'))
        session.append('sandbox/mode',dict(mode='danger-full-access'))
        result = await pending
        rows.append(dict(name='policy-abort',result=project(result),callerOwned=not settled.is_set()))
        release.set()
        await settled.wait()
        pending = asyncio.create_task(runtime.run(runtime.resolve(dict(program='while True:\n    pass',bindings=[],
            sandboxPolicy=dict(mode='danger-full-access',workspaceRoot=str(WORKSPACE))))))
        await asyncio.sleep(.05)
        await ctx.fiber.dispose()
        rows.append(dict(name='dispose',result=project(await pending)))
        assert not runtime.live and not runtime.runs and not runtime.processes.processes
    finally:
        await ctx.fiber.dispose()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE = output/'files'/'workspace'
    WORKSPACE.mkdir(parents=True)
    path = output/'input.json'
    path.write_text(json.dumps(dict(workspace=str(WORKSPACE))),encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_ptc_confinement.mts',
        'Actual Windows file-policy Node/Python process runs, partial enforcement, denied classification, empty model environment, timeout, standing-policy invalidation under temporary escalation, caller-owned nested work, owner disposal.',
        [Path(__file__).resolve(),ROOT/'dsh/code_runtime/confined_ptc.py',ROOT/'dsh/code_runtime/process.py',
         ROOT/'dsh/sandbox/runner_failure.py',ROOT/'dsh/sandbox/local.py',ROOT/'dsh/sandbox/windows_runner.py',
         ROOT/'dsh/sandbox/windows_acl.py'],prepare)
