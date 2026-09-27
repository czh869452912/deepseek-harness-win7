"""Pinned agent-presets invariant consumer contracts using real mounted presets."""
from types import SimpleNamespace
import pytest
from dsh.core.scope import create_scope, ScopeKey, scope_of, scope_parent_of
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.core.system_prompt import SystemPrompt
from dsh.diagnostics.invariants import InvariantRegistry, InvariantError
from dsh.presets import AgentPresets, live_preset_mounts
from dsh.presets.invariant import AgentPresetsInvariantPlugin

async def boot(tmp_path, roots=True):
    ctx=Context();ctx.baseUrl=str(tmp_path)
    await ctx.plugin(Loader);await ctx.plugin(SystemPrompt);await ctx.plugin(InvariantRegistry)
    directory=tmp_path/'standard';directory.mkdir()
    (directory/'agent.cordis.yml').write_text('[]\n',encoding='utf-8')
    await ctx.plugin(AgentPresets,{'default':'standard','roots':[{'path':str(tmp_path)}] if roots else [],'includeUserRoot':False})
    companion=await ctx.plugin(AgentPresetsInvariantPlugin)
    return ctx,companion

@pytest.mark.asyncio
async def test_late_global_service_is_rejected_and_companion_disposes(tmp_path):
    ctx,companion=await boot(tmp_path)
    try:
        presets=ctx.get('agentPresets');agent_ctx=create_scope(ctx, ScopeKey(object())).ctx
        await presets.mount(agent_ctx,'standard')
        mount=next(m for m in live_preset_mounts() if m.fiber.ctx.root is ctx)
        with pytest.raises(InvariantError,match='published process-global service'):
            mount.fiber.ctx.provide('lateService',object())
        await companion.dispose()
        mount.fiber.ctx.provide('afterCompanionDispose',object())
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_unjoined_agent_rejected_but_joined_and_cold_reads_allowed(tmp_path):
    ctx,_=await boot(tmp_path)
    try:
        prompt=ctx.get('system_prompt');presets=ctx.get('agentPresets')
        agent=SimpleNamespace(id='unjoined',ctx=create_scope(ctx, ScopeKey(object())).ctx)
        with pytest.raises(InvariantError,match='without joining any agent preset'):
            await prompt.assemble({'agent':agent})
        await presets.mount(agent.ctx,'standard')
        await prompt.assemble({'agent':agent})
        await prompt.assemble({})
        await prompt.assemble({'scope':object()})
    finally: await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_empty_roster_does_not_require_joining(tmp_path):
    ctx,_=await boot(tmp_path,False)
    try:
        await ctx.get('system_prompt').assemble({'agent':SimpleNamespace(id='bare',ctx=create_scope(ctx, ScopeKey(object())).ctx)})
    finally: await ctx.fiber.dispose()
