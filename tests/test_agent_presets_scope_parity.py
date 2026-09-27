"""Scope identity contracts from upstream agent-presets mount.spec.ts."""
import pytest
from dsh.core.scope import create_scope, ScopeKey, scope_of, scope_parent_of
from dsh.core.tools import ToolsPlugin
from test_agent_presets_upstream_parity import boot, seed

@pytest.mark.asyncio
async def test_standing_tools_are_scoped_and_recompose_keeps_context_ancestry(tmp_path):
    def contribute(ctx, config):
        ctx.get("tools").register_tool(name=config["label"], description="fixture", parameters={"type":"object"}, handler=lambda args: "ok")
    for name in ("alpha", "beta"):
        seed(tmp_path, name, "- id: tools\n  name: fixture:tools\n  config:\n    label: %s\n" % name)
    ctx, _, presets = await boot(tmp_path, {"fixture:tools":contribute})
    await ctx.plugin(ToolsPlugin)
    first = create_scope(ctx, ScopeKey("first"))
    second = create_scope(ctx, ScopeKey("second"))
    original_parent = first.ctx._parent
    try:
        await presets.mount(first.ctx, "alpha")
        await presets.mount(second.ctx, "beta")
        tools = ctx.get("tools")
        assert [t.name for t in tools.list_tools(scope_of(first.ctx))] == ["alpha"]
        assert [t.name for t in tools.list_tools(scope_of(second.ctx))] == ["beta"]
        assert tools.list_tools() == []
        assert first.ctx._parent is original_parent
        child = create_scope(ctx, ScopeKey("child"))
        assert presets.compose_from(child.ctx, first.ctx) == "alpha"
        assert scope_parent_of(scope_of(child.ctx)) is scope_parent_of(scope_of(first.ctx))
        await first.dispose()
        assert [t.name for t in tools.list_tools(scope_of(child.ctx))] == ["alpha"]
        seen = []
        ctx.on("tools/change", lambda: seen.append(presets.composed_preset(child.ctx)))
        await presets.recompose(child.ctx, "beta")
        assert seen == ["beta"]
        assert [t.name for t in tools.list_tools(scope_of(child.ctx))] == ["beta"]
    finally:
        await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_extended_context_without_scope_is_rejected(tmp_path):
    seed(tmp_path,"alpha","[]\n")
    ctx, _, presets = await boot(tmp_path,{})
    try:
        with pytest.raises(RuntimeError,match="unscoped"):
            await presets.mount(ctx.extend(),"alpha")
    finally:
        await ctx.fiber.dispose()

@pytest.mark.asyncio
async def test_real_factory_awaits_preset_setup_and_limits_model_tools(tmp_path):
    import asyncio
    from dsh.core.agent_loop import AgentLoopPlugin
    from dsh.core.agent import AgentPlugin
    from dsh.core.session import SessionPlugin
    from dsh.core.system_prompt import SystemPrompt
    from test_e2e_core_spine_strict_parity import StrictMockLlmAdapter
    def contribute(ctx, config):
        ctx.get("tools").register_tool(name=config["label"], description="fixture", parameters={"type":"object"}, handler=lambda args: "ok")
    for name in ("alpha", "beta"):
        seed(tmp_path,name,"- id: tools\n  name: fixture:tools\n  config:\n    label: %s\n" % name)
    ctx, _, presets = await boot(tmp_path,{"fixture:tools":contribute})
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(AgentLoopPlugin)
    adapter=StrictMockLlmAdapter([{"text":"done"}]);ctx.provide("llm",adapter)
    handles=[]
    try:
        for name in ("alpha","beta"):
            handles.append(await ctx.get("agents").create(session_id=name,setup=lambda c,n=name: presets.mount(c,n)))
        handles[0].agent.followup("List your tools")
        await asyncio.wait_for(handles[0].agent.when_idle(),5)
        assert [row["name"] for row in adapter.requests[0]["tools"]] == ["alpha"]
        assert ctx.get("tools").list_tools() == []
        with pytest.raises(Exception,match="unknown"):
            await ctx.get("agents").create(session_id="broken",setup=lambda c: presets.mount(c,"unknown"))
        assert ctx.get("agents").get("broken") is None
        assert ctx.get("sessions").get("broken") is None
    finally:
        for handle in handles: await handle.dispose()
        await ctx.fiber.dispose()
