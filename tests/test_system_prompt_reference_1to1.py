"""
SystemPrompt 1:1 Unit Tests matching reference/packages/core/system-prompt/tests/system-prompt.spec.ts.
Verifies:
1. First-party section order constants spacing and uniqueness.
2. Built-in identity & persona registration and prompt rendering.
3. Ordered section assembly, dynamic context snapshots, and tool schema collection.
4. Deterministic tie-breaking by section name.
5. Complete section override constraint after waterfall.
6. Strict variable {{var}} interpolation, escaping, and diagnostics.
7. Configured toolOrder insertion at <unlisted-tools>.
"""

import pytest
from dsh.cordis.context import Context
from dsh.core.system_prompt import (
    SystemPrompt,
    FIRST_PARTY_SECTION_ORDER,
    PERSONA_SECTION,
    TOOL_ORDER_REST,
    render_prompt,
    render_context_snapshot,
    render_context_sections,
)

IDENTITY = "You are an AI agent powered by DeepSeek Harness."


def test_first_party_section_placements():
    """Verify first-party section placements are unique, integral, and >= 10 apart."""
    orders = list(FIRST_PARTY_SECTION_ORDER.values())
    assert all(isinstance(o, int) for o in orders)
    assert len(set(orders)) == len(orders)
    sorted_orders = sorted(orders)
    assert all(sorted_orders[i] - sorted_orders[i - 1] >= 10 for i in range(1, len(sorted_orders)))


@pytest.mark.asyncio
async def test_builtin_sections_and_rendering():
    """Verify registration of harness identity and configured deployment persona."""
    ctx = Context()
    sp = SystemPrompt(ctx, {"persona": "You are DeepSeek Harness."})

    assembly = await sp.assemble()
    assert [s["name"] for s in assembly["sections"]] == ["harness:identity", "deployment:persona"]
    assert render_prompt(assembly) == f"{IDENTITY}\n\nYou are DeepSeek Harness."

    # Duplicate registration throws
    with pytest.raises(ValueError) as exc:
        sp.section({"name": "deployment:persona", "order": 0, "text": "imposter"})
    assert 'prompt section "deployment:persona" is already registered' in str(exc.value)


@pytest.mark.asyncio
async def test_persona_omitted_and_identity_omitted():
    """Verify empty persona and omitted identity options."""
    ctx1 = Context()
    sp1 = SystemPrompt(ctx1, {})
    assert render_prompt(await sp1.assemble()) == IDENTITY

    ctx2 = Context()
    sp2 = SystemPrompt(ctx2, {
        "includeHarnessIdentity": False,
        "persona": "You are a helpful assistant.",
    })
    assembly2 = await sp2.assemble()
    assert [s["name"] for s in assembly2["sections"]] == ["deployment:persona"]
    assert render_prompt(assembly2) == "You are a helpful assistant."


@pytest.mark.asyncio
async def test_runtime_context_suppression():
    """Verify suppressing runtime context drops contexts without evaluating them."""
    ctx = Context()
    sp = SystemPrompt(ctx, {"includeRuntimeContext": False})

    called = []
    sp.context({
        "name": "policy",
        "order": 0,
        "text": lambda c: called.append(True) or "policy text",
    })

    assembly = await sp.assemble()
    assert assembly["contexts"] == []
    assert len(called) == 0


@pytest.mark.asyncio
async def test_ordered_sections_contexts_and_tools():
    """Verify sections concatenated in order with context-resolved text and collected tools."""
    ctx = Context()
    sp = SystemPrompt(ctx, {"persona": "You are DeepSeek Harness."})

    sp.section({"name": "cwd", "order": 20, "text": lambda c: "cwd: /tmp"})
    sp.section({"name": "rules", "order": 10, "text": "Be precise."})
    sp.context({"name": "later", "order": 20, "text": lambda c: "context 2"})
    sp.context({"name": "earlier", "order": 10, "text": "context 1"})
    sp.tools(lambda c: {"schemas": [{"name": "echo", "description": "echo back", "parameters": {}}]})

    assembly = await sp.assemble()
    assert [s["name"] for s in assembly["sections"]] == ["harness:identity", "deployment:persona", "rules", "cwd"]
    assert [s["text"] for s in assembly["sections"]] == [IDENTITY, "You are DeepSeek Harness.", "Be precise.", "cwd: /tmp"]
    assert assembly["contexts"] == [
        {"name": "earlier", "text": "context 1"},
        {"name": "later", "text": "context 2"},
    ]
    assert assembly["tools"] == [{"name": "echo", "description": "echo back", "parameters": {}}]
    assert render_prompt(assembly) == f"{IDENTITY}\n\nYou are DeepSeek Harness.\n\nBe precise.\n\ncwd: /tmp"
    assert render_context_snapshot(assembly) == "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\ncontext 1\n\ncontext 2"


@pytest.mark.asyncio
async def test_breaks_equal_section_orders_by_name():
    """Verify ties in section order are broken by code-unit name."""
    for names in [["b_section", "a_section"], ["a_section", "b_section"]]:
        ctx = Context()
        sp = SystemPrompt(ctx, {"includeHarnessIdentity": False, "persona": ""})
        for name in names:
            sp.section({"name": name, "order": 10, "text": name})
        assembly = await sp.assemble()
        contributed = [s["name"] for s in assembly["sections"] if s["name"] != "deployment:persona"]
        assert contributed == ["a_section", "b_section"]


@pytest.mark.asyncio
async def test_complete_section_restoration_after_waterfall():
    """Verify single complete section is restored as sole section after waterfall."""
    ctx = Context()
    sp = SystemPrompt(ctx, {})

    sp.section({
        "name": "complete_policy",
        "order": 100,
        "text": "EXCLUSIVE SYSTEM PROMPT",
        "complete": True,
    })

    # Waterfall listener attempting to add extra sections
    def _on_assembly(assembly, context, next_fn):
        assembly["sections"].append({"name": "extra", "text": "extra text"})
        return next_fn(assembly)

    ctx.on("system-prompt/assemble", _on_assembly)

    assembly = await sp.assemble()
    assert len(assembly["sections"]) == 1
    assert assembly["sections"][0]["name"] == "complete_policy"
    assert assembly["sections"][0]["text"] == "EXCLUSIVE SYSTEM PROMPT"
    assert render_prompt(assembly) == "EXCLUSIVE SYSTEM PROMPT"


@pytest.mark.asyncio
async def test_multiple_complete_sections_fail():
    """Verify multiple complete sections make assembly fail loud."""
    ctx = Context()
    sp = SystemPrompt(ctx, {})

    sp.section({"name": "c1", "order": 10, "text": "complete 1", "complete": True})
    sp.section({"name": "c2", "order": 20, "text": "complete 2", "complete": True})

    with pytest.raises(ValueError) as exc:
        await sp.assemble()
    assert "multiple complete prompt sections are active" in str(exc.value)


@pytest.mark.asyncio
async def test_strict_variable_interpolation():
    """Verify strict variable {{var}} interpolation in prompt rendering."""
    ctx = Context()
    sp = SystemPrompt(ctx, {"includeHarnessIdentity": False})

    sp.section({"name": "greeting", "order": 1, "text": "Hello {{user_name}}, welcome to {{project_name}}!"})
    sp.variable("user_name", lambda c: "Alice")
    sp.variable("project_name", lambda c: "Harness")

    assembly = await sp.assemble()
    assert render_prompt(assembly) == "Hello Alice, welcome to Harness!"

    # Unknown variable error
    sp.section({"name": "bad_var", "order": 2, "text": "Missing {{unknown_var}}"})
    assembly_bad = await sp.assemble()
    with pytest.raises(ValueError) as exc:
        render_prompt(assembly_bad)
    assert 'unknown prompt variable "{{unknown_var}}"' in str(exc.value)


@pytest.mark.asyncio
async def test_configured_tool_order():
    """Verify toolOrder with <unlisted-tools> marker."""
    ctx = Context()
    sp = SystemPrompt(ctx, {
        "toolOrder": ["tool_z", TOOL_ORDER_REST, "tool_a"],
    })

    sp.tools(lambda c: {
        "schemas": [
            {"name": "tool_a", "description": "a"},
            {"name": "tool_b", "description": "b"},
            {"name": "tool_c", "description": "c"},
            {"name": "tool_z", "description": "z"},
        ],
    })

    assembly = await sp.assemble()
    names = [t["name"] for t in assembly["tools"]]
    assert names == ["tool_z", "tool_b", "tool_c", "tool_a"]
