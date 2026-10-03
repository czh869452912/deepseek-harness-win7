from pathlib import Path
import sys

import pytest

from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.core.abort import AbortController
from dsh.core.tools import ToolExecutionInput
from test_acp_session_controls import boot_profile, stop_profile


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
@pytest.mark.parametrize('backend', ['jsonl', 'sqlite'])
async def test_canonical_profile_actual_tools_consumer_owns_acp_child_exit(tmp_path, backend, monkeypatch):
    runtime, bridge, unused = await boot_profile(tmp_path, backend, monkeypatch)
    ctx = runtime['ctx']
    children = []
    try:
        for package in ('subprocess-local', 'subagent'):
            await ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-' + package))
        service = ctx.get('subprocess')
        spawn = service.spawn
        def capture(spec):
            child = spawn(spec)
            children.append(child)
            return child
        service.spawn = capture
        provider = await ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-subagent-acp'), {
            'command': sys.executable, 'args': [str(ROOT / 'scripts/oracles/subagent_acp_peer.py')],
            'env': {'PROBE_TEXT': 'actual child result'}, 'disposeEofGraceMs': 1000, 'disposeGraceMs': 100})
        mounted = await ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-tool-subagent'), {
            'provider': 'acp', 'maxDepth': 'provider-managed', 'enableRunInBackground': False})
        created = await bridge.new_session(ctx, {'cwd': str(tmp_path), 'mcpServers': []})
        agent = bridge.sessions[created['sessionId']].agent
        result = await ctx.get('tools').execute(ToolExecutionInput('actual-acp-delegation', 'subagent',
            {'description': 'child work', 'prompt': 'explicit child task'}, agent=agent, signal=AbortController().signal))
        assert not result.is_error
        assert result.value['kind'] == 'foreground'
        assert result.value['output'] == [{'type': 'text', 'text': 'actual child result'}]
        assert result.content == [{'type': 'text', 'text': 'actual child result'}]
        assert result.value['runId'] != 'same-child-id'
        assert len(children) == 1
        assert (await children[0].done).exitCode == 0 and await children[0].wait_for_exit()
        assert ctx.get('agents').list() == [agent]
        await provider.dispose()
        assert ctx.get('subagents').list() == []
        assert not ctx.get('tools').list_tools(agent)
        await mounted.dispose()
        await bridge.close_session(ctx, created)
        assert not ctx.get('agents').list()
    finally:
        await stop_profile(runtime)
    assert all(child.done.done() and child.done.result().exitCode == 0 for child in children)
