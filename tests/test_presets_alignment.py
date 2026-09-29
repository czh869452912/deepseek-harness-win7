"""Actual upstream presets join distinct scopes in one formal Web host."""
import sys
import pytest
from canonical_web_fixture import web_context, close_web_context


@pytest.mark.asyncio
async def test_minimal_and_standard_preset_isolation(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        controller = ctx.get('sessionController')
        agents = {}
        for preset in ('minimal', 'standard'):
            await controller.create(dict(cwd=str(tmp_path), sessionId=preset, agentPreset=preset))
            agents[preset] = ctx.get('agents').get(preset)
        names = {preset: {tool.name for tool in ctx.get('tools').list_tools(scope=agent.ctx)} for preset, agent in agents.items()}
        shell = 'pwsh' if sys.platform == 'win32' else 'bash'
        assert names['minimal'] == {'str_replace_editor', shell}
        assert {'read', 'write', 'edit', shell, 'skill', 'exit_plan_mode', 'create_goal'} <= names['standard']
        assert agents['minimal'].ctx.get('compaction') is None
        assert 'compact' not in names['minimal']
        assert 'exit_plan_mode' not in names['minimal']
        assert ctx.get('compaction') is None
    finally:
        await close_web_context(ctx)
