"""
1:1 port of reference/packages/core/system-prompt/tests/scoped.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock
import pytest

from dsh.cordis.context import Context
from dsh.core.scope import Scope, create_scope, scope_of
from dsh.core.system_prompt import (
    SystemPrompt,
    TOOL_ORDER_REST,
    render_context_snapshot,
    render_prompt,
)


def schema(name: str) -> Dict[str, Any]:
    return {"name": name, "description": f"tool {name}", "parameters": {}}


async def mount(config: Optional[Dict[str, Any]] = None) -> Context:
    ctx = Context()
    await ctx.plugin(SystemPrompt, config or {})
    return ctx


async def mint_scope(ctx: Context, name: str) -> Scope:
    scope_holder: List[Scope] = []

    def plugin_fn(inner: Context):
        sc = create_scope(inner, {"name": name})
        scope_holder.append(sc)

    setattr(plugin_fn, "inject", ["systemPrompt"])
    await ctx.plugin(plugin_fn)
    return scope_holder[0]


def scope_key_of(scope: Scope) -> Any:
    return scope_of(scope.ctx)


@pytest.mark.asyncio
async def test_scoped_persona_shadows_deployment_persona():
    ctx = await mount({"persona": "You are the deployment."})
    scope = await mint_scope(ctx, "child")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")
    sp_scoped.section({"name": "deployment:persona", "order": 0, "text": "You run tests."})

    sp: SystemPrompt = ctx.get("systemPrompt")
    scoped = render_prompt(await sp.assemble({"scope": scope_key_of(scope)}))
    glob = render_prompt(await sp.assemble())
    assert "You run tests." in scoped
    assert "You are the deployment." not in scoped
    assert "You are the deployment." in glob
    assert "You run tests." not in glob


@pytest.mark.asyncio
async def test_scoped_only_sections_join_scope_alone_and_disposal_removes():
    ctx = await mount()
    scope = await mint_scope(ctx, "child")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")
    sp_scoped.section({"name": "child:extra", "order": 50, "text": "Extra guidance."})

    sp: SystemPrompt = ctx.get("systemPrompt")
    assert "Extra guidance." in render_prompt(await sp.assemble({"scope": scope_key_of(scope)}))
    assert "Extra guidance." not in render_prompt(await sp.assemble())
    await scope.dispose()
    assert "Extra guidance." not in render_prompt(await sp.assemble({"scope": scope_key_of(scope)}))


@pytest.mark.asyncio
async def test_duplicate_names_throw_per_layer():
    ctx = await mount()
    scope = await mint_scope(ctx, "child")
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")

    sp.section({"name": "x", "order": 1, "text": "a"})
    with pytest.raises(ValueError, match=r"agent\.ctx"):
        sp.section({"name": "x", "order": 1, "text": "b"})

    sp_scoped.section({"name": "y", "order": 1, "text": "a"})
    with pytest.raises(ValueError, match=r"already registered in this scope"):
        sp_scoped.section({"name": "y", "order": 1, "text": "b"})


@pytest.mark.asyncio
async def test_shadows_global_section_before_evaluating_text_provider():
    ctx = await mount()
    scope = await mint_scope(ctx, "child")
    global_text = MagicMock(return_value="global text")
    scoped_text = MagicMock(return_value="scoped text")

    sp: SystemPrompt = ctx.get("systemPrompt")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")
    sp.section({"name": "shared", "order": 1, "text": global_text})
    sp_scoped.section({"name": "shared", "order": 1, "text": scoped_text})

    assembly = await sp.assemble({"scope": scope_key_of(scope)})
    sec = next(s for s in assembly["sections"] if s["name"] == "shared")
    assert sec["text"] == "scoped text"
    assert global_text.call_count == 0
    assert scoped_text.call_count == 1


@pytest.mark.asyncio
async def test_scoped_variable_shadows_global_name_twin():
    ctx = await mount({"persona": "Mode: {{mode}}."})
    scope = await mint_scope(ctx, "child")
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")

    sp.variable("mode", lambda _: "normal")
    sp_scoped.variable("mode", lambda _: "strict")

    assert "Mode: strict." in render_prompt(await sp.assemble({"scope": scope_key_of(scope)}))
    assert "Mode: normal." in render_prompt(await sp.assemble())


@pytest.mark.asyncio
async def test_same_layer_variable_duplicates_throw_and_scope_cleans_up():
    ctx = await mount()
    scope = await mint_scope(ctx, "child")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")

    sp_scoped.variable("v", lambda _: "1")
    with pytest.raises(ValueError, match=r"already registered in this scope"):
        sp_scoped.variable("v", lambda _: "2")

    await scope.dispose()
    again = await mint_scope(ctx, "child2")
    again_sp: SystemPrompt = again.ctx.get("systemPrompt")
    again_sp.variable("v", lambda _: "3")


@pytest.mark.asyncio
async def test_defers_scoped_variable_replacing_last_provider():
    ctx = await mount({"persona": "Mode: {{mode}}."})
    scope = await mint_scope(ctx, "child")
    key = scope_key_of(scope)
    calls: List[str] = []

    sp: SystemPrompt = ctx.get("systemPrompt")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")
    sp_scoped.section({"name": "scope:sibling", "order": 1, "text": "Scoped."})

    dispose_holder = []
    def first_prov(context):
        calls.append("first")
        if dispose_holder:
            dispose_holder[0]()
        sp_scoped.variable("mode", lambda ctx: (calls.append("replacement"), "replacement")[1])
        return "first"

    d = sp_scoped.variable("mode", first_prov)
    dispose_holder.append(d)

    assert "Mode: first." in render_prompt(await sp.assemble({"scope": key}))
    assert calls == ["first"]
    assert "Mode: replacement." in render_prompt(await sp.assemble({"scope": key}))
    assert calls == ["first", "replacement"]


@pytest.mark.asyncio
async def test_scoped_context_shadows_global_and_cleans_up():
    ctx = await mount()
    scope = await mint_scope(ctx, "child-context")
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")

    sp.context({"name": "policy", "order": 1, "text": "global policy"})
    sp_scoped.context({"name": "policy", "order": 1, "text": "scoped policy"})
    with pytest.raises(ValueError, match=r'prompt context "policy" is already registered in this scope'):
        sp_scoped.context({"name": "policy", "order": 2, "text": "duplicate"})

    assert "scoped policy" in render_context_snapshot(await sp.assemble({"scope": scope_key_of(scope)}))
    assert "global policy" in render_context_snapshot(await sp.assemble())

    await scope.dispose()
    assert "global policy" in render_context_snapshot(await sp.assemble({"scope": scope_key_of(scope)}))


@pytest.mark.asyncio
async def test_suppresses_all_context_for_one_scope_and_restores():
    ctx = await mount()
    scope = await mint_scope(ctx, "suppressed-context")
    key = scope_key_of(scope)
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")

    sp.context({"name": "policy", "order": 1, "text": "global policy"})
    dispose = sp_scoped.suppress_runtime_context()

    suppressed = await sp.assemble({"scope": key})
    assert suppressed["contexts"] == []
    glob = await sp.assemble()
    assert "global policy" in render_context_snapshot(glob)

    dispose()
    assert "global policy" in render_context_snapshot(await sp.assemble({"scope": key}))


@pytest.mark.asyncio
async def test_scoped_tool_providers_consulted_only_for_scope():
    ctx = await mount()
    scope = await mint_scope(ctx, "child")
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")

    sp.tools(lambda _: {"schemas": [schema("global_tool")]})
    sp_scoped.tools(lambda _: {"schemas": [schema("scoped_tool")]})

    scoped = await sp.assemble({"scope": scope_key_of(scope)})
    glob = await sp.assemble()
    assert [t["name"] for t in scoped["tools"]] == ["global_tool", "scoped_tool"]
    assert [t["name"] for t in glob["tools"]] == ["global_tool"]


@pytest.mark.asyncio
async def test_disposing_scoped_tool_provider_empties_layer():
    ctx = await mount()
    scope = await mint_scope(ctx, "child")
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp_scoped: SystemPrompt = scope.ctx.get("systemPrompt")

    dispose = sp_scoped.tools(lambda _: {"schemas": [schema("scoped_tool")]})
    dispose()
    after = await sp.assemble({"scope": scope_key_of(scope)})
    assert [t["name"] for t in after["tools"]] == []

    sp_scoped.tools(lambda _: {"schemas": [schema("again")]})
    again = await sp.assemble({"scope": scope_key_of(scope)})
    assert [t["name"] for t in again["tools"]] == ["again"]


@pytest.mark.asyncio
async def test_tool_order_restricted_away_is_normal_absence_typo_throws():
    ctx = await mount({"toolOrder": ["bash", TOOL_ORDER_REST]})
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.tools(lambda _: {
        "schemas": [schema("read")],
        "knownNames": ["read", "bash"],
    })
    assembly = await sp.assemble()
    assert [t["name"] for t in assembly["tools"]] == ["read"]

    bad = await mount({"toolOrder": ["basj", TOOL_ORDER_REST]})
    bad_sp: SystemPrompt = bad.get("systemPrompt")
    bad_sp.tools(lambda _: {"schemas": [schema("read")], "knownNames": ["read", "bash"]})
    with pytest.raises(ValueError, match=r'toolOrder lists unregistered tool "basj"; known tools: bash, read'):
        await bad_sp.assemble()


@pytest.mark.asyncio
async def test_scoped_assemble_listener_shapes_only_own_scope():
    ctx = await mount()
    scope = await mint_scope(ctx, "child")
    sp: SystemPrompt = ctx.get("systemPrompt")
    shaped: List[Any] = []

    async def listener(assembly, context, next_fn=None):
        shaped.append(context.get("scope"))
        res = await next_fn() if next_fn else assembly
        res["sections"].append({"name": "listener:extra", "text": "listener text"})
        return res

    scope.ctx.on("system-prompt/assemble", listener)

    scoped = await sp.assemble({"scope": scope_key_of(scope)})
    glob = await sp.assemble()
    assert any(s["name"] == "listener:extra" for s in scoped["sections"])
    assert not any(s["name"] == "listener:extra" for s in glob["sections"])
    assert len(shaped) == 1
