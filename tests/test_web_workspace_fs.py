"""Filesystem operations use the calling session's workspace and sandbox."""
import pytest

from canonical_web_fixture import web_context, close_web_context
from dsh.core.tools import ToolExecutionInput
from dsh.core.abort import NEVER_ABORTED


@pytest.mark.asyncio
async def test_web_filesystem_cwd_and_policy_are_per_session(tmp_path, monkeypatch):
    # Pytest workspaces live beneath the platform-wide temp grant. Restrict
    # this test to the supplied workspace root so a wrong session is visible.
    monkeypatch.setattr('dsh.fs.fs_sandbox.writable_roots', lambda policy: [policy['workspaceRoot']])
    ctx = await web_context(tmp_path / 'home')
    try:
        agents = []
        for name in ('first', 'second'):
            workspace = tmp_path / name
            workspace.mkdir()
            await ctx.get('sessionController').create(dict(sessionId=name, cwd=str(workspace), agentPreset='standard'))
            agents.append(ctx.get('agents').get(name))
        tools = ctx.get('tools')
        serial = [0]
        async def call(agent, name, **args):
            serial[0] += 1
            return await tools.execute(ToolExecutionInput('fs-%s' % serial[0], name, args,
                                                         agent=agent, signal=NEVER_ABORTED))
        for agent, content in zip(agents, ('first content', 'second content')):
            result = await call(agent, 'write', file_path='same-name.txt', content=content)
            assert not result.is_error, result.content
            assert (tmp_path / agent.id / 'same-name.txt').read_text(encoding='utf-8') == content
            read = await call(agent, 'read', file_path='same-name.txt')
            assert content in str(read.content)
            edited = await call(agent, 'edit', file_path='same-name.txt', old_string=content, new_string='edited ' + content)
            assert not edited.is_error, edited.content
        outside = tmp_path / 'second' / 'forbidden.txt'
        denied = await call(agents[0], 'write', file_path=str(outside), content='must not cross workspace')
        assert denied.is_error and not outside.exists()
        agents[0].session.append('sandbox/mode', {'mode': 'read-only'})
        denied = await call(agents[0], 'write', file_path='denied.txt', content='must not write')
        assert denied.is_error and not (tmp_path / 'first' / 'denied.txt').exists()
    finally:
        await close_web_context(ctx)
