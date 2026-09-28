from types import SimpleNamespace
import os
import pytest

from dsh.core.abort import AbortController
from dsh.core.scope import scope_of
from dsh.shell.canonical_tool_pwsh import CanonicalToolPwsh, render_foreground
from test_subagent_in_process import setup


class Shell:
    sandboxMode = 'read-only'

    def __init__(self):
        self.requests = []

    def resolve(self, request):
        return dict(request, timeoutMs=1000)

    async def run(self, spec):
        self.requests.append(spec)
        return dict(exitCode=0, signal=None, timedOut=False, aborted=False, timeoutMs=1000,
                    stdout=dict(text='ok', truncated=False), stderr=dict(text='', truncated=False))


@pytest.mark.asyncio
async def test_tool_resolves_session_policy_approval_before_spawn_and_unloads(tmp_path):
    ctx, _, parent = await setup()
    shell = Shell()
    ctx.set_service('shell', shell)
    ctx.set_service('shellEnv', SimpleNamespace(collect=lambda execution: {'DSH_TEST': 'trusted'}))
    ctx.set_service('sandboxPolicy', SimpleNamespace(resolve=lambda request: dict(mode='read-only', workspaceRoot=str(tmp_path))))
    asks = []
    outcome = ['rejected']

    async def approve(request):
        asks.append(request)
        return outcome[0]

    ctx.set_service('approval', SimpleNamespace(request=approve))
    fiber = await ctx.plugin(CanonicalToolPwsh)
    tool = ctx.get('tools').get('pwsh', scope_of(parent.agent.ctx))
    execution = SimpleNamespace(agent=parent.agent, signal=AbortController().signal, callId='call-pwsh')
    args = dict(command='Get-Content file', description='Read file')
    try:
        result = await tool.execute(args, execution)
        assert result['kind'] == 'foreground'
        assert shell.requests[0]['sandboxPolicy']['mode'] == 'read-only'
        assert shell.requests[0]['dshEnv'] == {'DSH_TEST': 'trusted'}
        escalated = dict(args, sandbox_permissions='workspace-write', justification='Need the workspace write')
        with pytest.raises(ValueError, match='rejected'):
            await tool.execute(escalated, execution)
        assert len(shell.requests) == 1
        assert asks[0]['callId'] == 'call-pwsh'
        outcome[0] = 'allowed-once'
        await tool.execute(escalated, execution)
        assert shell.requests[-1]['sandboxPolicy']['mode'] == 'workspace-write'
        await tool.execute(args, execution)
        assert shell.requests[-1]['sandboxPolicy']['mode'] == 'read-only'
        with pytest.raises(ValueError, match='background jobs unavailable'):
            await tool.execute(dict(args, run_in_background=True), execution)
        assert len(shell.requests) == 3
        await fiber.dispose()
        assert ctx.get('tools').get('pwsh', scope_of(parent.agent.ctx)) is None
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


def test_denial_and_timeout_keep_exit_marker_last():
    value = dict(kind='foreground', stdout=dict(text='', truncated=False), stderr=dict(text='denied', truncated=False),
                 exitCode=1, signal=None, timedOut=True, timeoutMs=10, sandbox=dict(mode='read-only', denied=True))
    rendered = render_foreground(value, True)
    assert '[sandbox: file access denied under read-only mode]' in rendered
    assert '[timed out after 10ms]' in rendered
    assert rendered.endswith('[exit code: 1]')


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows tool execution')
@pytest.mark.asyncio
async def test_real_tool_uses_shell_and_detached_job_ownership(tmp_path):
    from dsh.subprocess.local import LocalSubprocessRuntime
    from dsh.sandbox.local import LocalSandboxProvider
    from dsh.sandbox.sandbox_policy import SandboxPolicyService
    from dsh.shell.pwsh_executor import SandboxPwshExecutor
    from dsh.jobs.local import LocalJobRegistry
    ctx, _, parent = await setup()
    ctx.set_service('shellEnv', SimpleNamespace(collect=lambda execution: {'DSH_TEST': 'trusted'}))
    try:
        await ctx.plugin(LocalSubprocessRuntime)
        await ctx.plugin(LocalSandboxProvider)
        await ctx.plugin(SandboxPolicyService, dict(mode='workspace-write', workspaceRoot=str(tmp_path)))
        await ctx.plugin(SandboxPwshExecutor, dict(cwd=str(tmp_path)))
        await ctx.plugin(LocalJobRegistry)
        await ctx.plugin(CanonicalToolPwsh)
        tool = ctx.get('tools').get('pwsh', scope_of(parent.agent.ctx))
        execution = SimpleNamespace(agent=parent.agent, signal=AbortController().signal)
        args = dict(command="Write-Output $env:DSH_TEST", description='Read trusted environment')
        value = await tool.execute(args, execution)
        assert value['stdout']['text'].strip() == 'trusted'
        assert value['sandbox']['enforcement'] == 'partial'
        background = dict(args, command="Start-Sleep -Milliseconds 200; Write-Output 'finished'", run_in_background=True, timeoutMs=1)
        with pytest.raises(ValueError, match='controller'):
            await tool.execute(background, execution)
        jobs = ctx.get('jobs')
        jobs.attach_controller('test')
        controller = AbortController()
        execution.signal = controller.signal
        value = await tool.execute(background, execution)
        controller.abort('caller finished')
        snapshot = await jobs.wait(value['jobId'], 8000, parent.agent)
        assert snapshot['status'] == 'completed'
        output = jobs.read(value['jobId'], parent.agent)
        assert 'finished' in output['text']
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()
