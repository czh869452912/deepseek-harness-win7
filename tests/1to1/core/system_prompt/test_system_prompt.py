"""
1:1 port of reference/packages/core/system-prompt/tests/system-prompt.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import math
from typing import Any, Dict, List, Optional
import pytest

from dsh.cordis import Context
from dsh.core.system_prompt import (
    FIRST_PARTY_SECTION_ORDER,
    PromptAssembly,
    SystemPrompt,
    render_context_snapshot,
    render_prompt,
)

BUILT_IN = ["harness:identity", "deployment:persona"]
IDENTITY = "You are an AI agent powered by DeepSeek Harness."


def contributed(assembly: PromptAssembly) -> List[Any]:
    return [s for s in assembly.sections if s.name not in BUILT_IN]


def test_first_party_section_placements_unique_integral_and_at_least_ten_apart():
    orders = list(FIRST_PARTY_SECTION_ORDER.values())
    assert all(isinstance(o, int) for o in orders)
    assert len(set(orders)) == len(orders)
    sorted_orders = sorted(orders)
    assert all(sorted_orders[i + 1] - sorted_orders[i] >= 10 for i in range(len(sorted_orders) - 1))


class TestBuiltInSections:
    @pytest.mark.asyncio
    async def test_registers_harness_identity_and_configured_deployment_persona(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt, {"persona": "You are DeepSeek Harness."})

        assembly = await ctx.systemPrompt.assemble()
        assert [s.name for s in assembly.sections] == [
            "harness:identity",
            "deployment:persona",
        ]
        assert render_prompt(assembly) == f"{IDENTITY}\n\nYou are DeepSeek Harness."

        with pytest.raises(Exception, match='prompt section "deployment:persona" is already registered'):
            ctx.systemPrompt.section({"name": "deployment:persona", "order": 0, "text": "imposter"})

    @pytest.mark.asyncio
    async def test_renders_no_persona_section_for_persona_less_deployment(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        assert render_prompt(await ctx.systemPrompt.assemble()) == IDENTITY

    @pytest.mark.asyncio
    async def test_can_omit_harness_identity_for_deployment_that_owns_complete_persona(self):
        ctx = Context()
        await ctx.plugin(
            SystemPrompt,
            {
                "includeHarnessIdentity": False,
                "persona": "You are a helpful software engineer assistant.",
            },
        )

        assembly = await ctx.systemPrompt.assemble()
        assert [s.name for s in assembly.sections] == ["deployment:persona"]
        assert render_prompt(assembly) == "You are a helpful software engineer assistant."

    @pytest.mark.asyncio
    async def test_can_suppress_runtime_context_without_evaluating_providers(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt, {"includeRuntimeContext": False})
        provider_calls = 0

        def policy_text(ctx_param=None):
            nonlocal provider_calls
            provider_calls += 1
            return f"policy {provider_calls}"

        ctx.systemPrompt.context({
            "name": "policy",
            "order": 0,
            "text": policy_text,
        })

        async def on_assemble(assembly, _context, next_fn):
            assembly.contexts.append({"name": "late", "text": "late context"})
            return await next_fn()

        ctx.on("system-prompt/assemble", on_assemble)

        assembly = await ctx.systemPrompt.assemble()
        assert assembly.contexts == []
        assert provider_calls == 0

    @pytest.mark.asyncio
    async def test_tolerates_schema_bypassing_direct_construction(self):
        ctx = Context()
        service = SystemPrompt(ctx, {})
        assert render_prompt(await service.assemble()) == IDENTITY


@pytest.mark.asyncio
async def test_assembles_sections_in_order_with_context_resolved_text_and_collected_tools():
    ctx = Context()
    await ctx.plugin(SystemPrompt, {"persona": "You are DeepSeek Harness."})

    ctx.systemPrompt.section({"name": "cwd", "order": 20, "text": lambda c=None: "cwd: /tmp"})
    ctx.systemPrompt.section({"name": "rules", "order": 10, "text": "Be precise."})
    ctx.systemPrompt.context({"name": "later", "order": 20, "text": lambda c=None: "context 2"})
    ctx.systemPrompt.context({"name": "earlier", "order": 10, "text": lambda c=None: "context 1"})
    ctx.systemPrompt.tools(lambda c=None: {"schemas": [{"name": "echo", "description": "echo back", "parameters": {}}]})

    assembly = await ctx.systemPrompt.assemble()
    assert [s.name for s in assembly.sections] == ["harness:identity", "deployment:persona", "rules", "cwd"]
    assert [s.text for s in assembly.sections] == [IDENTITY, "You are DeepSeek Harness.", "Be precise.", "cwd: /tmp"]
    assert assembly.contexts == [
        {"name": "earlier", "text": "context 1"},
        {"name": "later", "text": "context 2"},
    ]
    assert assembly.tools == [{"name": "echo", "description": "echo back", "parameters": {}}]
    assert assembly.variables == {}
    assert render_prompt(assembly) == f"{IDENTITY}\n\nYou are DeepSeek Harness.\n\nBe precise.\n\ncwd: /tmp"
    assert render_context_snapshot(assembly) == (
        "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\ncontext 1\n\ncontext 2"
    )


@pytest.mark.asyncio
async def test_breaks_equal_section_orders_by_code_unit_name():
    for names in [["äther", "zeta"], ["zeta", "äther"]]:
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        for name in names:
            ctx.systemPrompt.section({"name": name, "order": 10, "text": name})
        assert [s.name for s in contributed(await ctx.systemPrompt.assemble())] == ["zeta", "äther"]


@pytest.mark.asyncio
async def test_resolves_section_text_providers_against_assemble_context():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    calls = 0

    def dynamic_text(context: Dict[str, Any]) -> str:
        nonlocal calls
        calls += 1
        who = context.get("who", "nobody") if isinstance(context, dict) else "nobody"
        return f"call {calls} for {who}"

    ctx.systemPrompt.section({
        "name": "dynamic",
        "order": 0,
        "text": dynamic_text,
    })

    r1 = await ctx.systemPrompt.assemble({"who": "alice"})
    assert contributed(r1)[0].text == "call 1 for alice"
    r2 = await ctx.systemPrompt.assemble()
    assert contributed(r2)[0].text == "call 2 for nobody"


@pytest.mark.asyncio
async def test_removes_contributions_when_contributing_fiber_is_disposed():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    def inner_plugin(inner: Context):
        inner.systemPrompt.section({"name": "scoped", "order": 0, "text": "scoped section"})
        inner.systemPrompt.context({"name": "scoped-context", "order": 0, "text": "scoped context"})
        inner.systemPrompt.tools(lambda c=None: {"schemas": [{"name": "scoped-tool", "description": "", "parameters": {}}]})
        inner.systemPrompt.variable("scoped_var", lambda c=None: "v")

    inner_plugin.inject = ["systemPrompt"]
    fiber = await ctx.plugin(inner_plugin)

    before = await ctx.systemPrompt.assemble()
    assert len(contributed(before)) == 1
    assert len(before.contexts) == 1
    assert before.variables == {"scoped_var": "v"}

    await fiber.dispose()
    assembly = await ctx.systemPrompt.assemble()
    assert len(contributed(assembly)) == 0
    assert len(assembly.contexts) == 0
    assert [s.name for s in assembly.sections] == BUILT_IN
    assert len(assembly.tools) == 0
    assert assembly.variables == {}


@pytest.mark.asyncio
async def test_rejects_duplicate_section_name():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    ctx.systemPrompt.section({"name": "dup", "order": 0, "text": "first"})
    with pytest.raises(Exception, match='prompt section "dup" is already registered'):
        ctx.systemPrompt.section({"name": "dup", "order": 1, "text": "second"})

    assembly = await ctx.systemPrompt.assemble()
    assert [s.text for s in contributed(assembly)] == ["first"]


@pytest.mark.asyncio
async def test_rejects_non_finite_section_order():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    with pytest.raises(Exception, match="order must be a finite number"):
        ctx.systemPrompt.section({"name": "bad-order", "order": float("nan"), "text": "x"})
    assert contributed(await ctx.systemPrompt.assemble()) == []


@pytest.mark.asyncio
async def test_rejects_duplicate_and_non_finite_context_registrations():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    ctx.systemPrompt.context({"name": "policy", "order": 1, "text": "first"})
    with pytest.raises(Exception, match='prompt context "policy" is already registered'):
        ctx.systemPrompt.context({"name": "policy", "order": 2, "text": "second"})
    with pytest.raises(Exception, match='prompt context "bad" order must be a finite number'):
        ctx.systemPrompt.context({"name": "bad", "order": float("nan"), "text": "x"})
    assert (await ctx.systemPrompt.assemble()).contexts == [{"name": "policy", "text": "first"}]


@pytest.mark.asyncio
async def test_rolls_back_section_when_change_listener_throws():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    threw = False
    def on_change():
        nonlocal threw
        if not threw:
            threw = True
            raise RuntimeError("boom change listener")

    off = ctx.on("system-prompt/change", on_change)

    with pytest.raises(RuntimeError, match="boom change listener"):
        ctx.systemPrompt.section({"name": "p", "order": 0, "text": "persona"})
    assert len(contributed(await ctx.systemPrompt.assemble())) == 0

    off()
    ctx.systemPrompt.section({"name": "p", "order": 0, "text": "persona"})
    assert [s.name for s in contributed(await ctx.systemPrompt.assemble())] == ["p"]


@pytest.mark.asyncio
async def test_rolls_back_tool_provider_when_change_listener_throws():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    threw = False
    def on_change():
        nonlocal threw
        if not threw:
            threw = True
            raise RuntimeError("boom change listener")

    off = ctx.on("system-prompt/change", on_change)

    with pytest.raises(RuntimeError, match="boom change listener"):
        ctx.systemPrompt.tools(lambda c=None: {"schemas": [{"name": "t", "description": "", "parameters": {}}]})
    assert len((await ctx.systemPrompt.assemble()).tools) == 0

    off()
    ctx.systemPrompt.tools(lambda c=None: {"schemas": [{"name": "t", "description": "", "parameters": {}}]})
    assert [t.name for t in (await ctx.systemPrompt.assemble()).tools] == ["t"]


@pytest.mark.asyncio
async def test_snapshots_tool_provider_membership_before_evaluating():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    added = False

    def tool_provider(c=None):
        nonlocal added
        if not added:
            added = True
            ctx.systemPrompt.tools(lambda c2=None: {"schemas": [{"name": "late", "description": "", "parameters": {}}]})
        return {"schemas": [{"name": "first", "description": "", "parameters": {}}]}

    ctx.systemPrompt.tools(tool_provider)

    r1 = await ctx.systemPrompt.assemble()
    assert [t.name for t in r1.tools] == ["first"]
    r2 = await ctx.systemPrompt.assemble()
    assert [t.name for t in r2.tools] == ["first", "late"]


@pytest.mark.asyncio
async def test_rolls_back_variable_when_change_listener_throws():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    threw = False
    def on_change():
        nonlocal threw
        if not threw:
            threw = True
            raise RuntimeError("boom change listener")

    off = ctx.on("system-prompt/change", on_change)

    with pytest.raises(RuntimeError, match="boom change listener"):
        ctx.systemPrompt.variable("v", lambda c=None: "x")
    assert (await ctx.systemPrompt.assemble()).variables == {}

    off()
    ctx.systemPrompt.variable("v", lambda c=None: "x")
    assert (await ctx.systemPrompt.assemble()).variables == {"v": "x"}


@pytest.mark.asyncio
async def test_composes_multiple_waterfall_listeners_in_order_with_context():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    ctx.systemPrompt.section({"name": "base", "order": 10, "text": "base"})

    contexts: List[Any] = []

    async def listener_a(assembly, context, next_fn):
        contexts.append(context)
        assembly.sections.append({"name": "from-a", "text": "a"})
        return await next_fn()

    ctx.on("system-prompt/assemble", listener_a)

    seen: List[List[str]] = []

    async def listener_b(assembly, _context, next_fn):
        seen.append([s.name for s in assembly.sections])
        return await next_fn()

    ctx.on("system-prompt/assemble", listener_b)

    passed = {"marker": True}
    assembly = await ctx.systemPrompt.assemble(passed)
    assert seen == [["harness:identity", "deployment:persona", "base", "from-a"]]
    assert [s.name for s in assembly.sections] == ["harness:identity", "deployment:persona", "base", "from-a"]
    assert contexts[0] == passed


@pytest.mark.asyncio
async def test_lets_waterfall_listener_short_circuit_by_not_calling_next():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    ctx.systemPrompt.section({"name": "real", "order": 0, "text": "real"})

    async def short_circuit(*args):
        return PromptAssembly(sections=[], contexts=[], tools=[], variables={})

    ctx.on("system-prompt/assemble", short_circuit)

    assembly = await ctx.systemPrompt.assemble()
    assert len(assembly.sections) == 0


@pytest.mark.asyncio
async def test_restores_one_complete_section_after_waterfall():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    ctx.systemPrompt.section({"name": "complete", "order": 10, "text": "Exact prompt.", "complete": True})
    ctx.systemPrompt.section({"name": "extra", "order": 20, "text": "extra"})

    async def mutator(assembly, _context, next_fn):
        complete = next((s for s in assembly.sections if s.name == "complete"), None)
        if complete is None:
            raise RuntimeError("complete section missing before waterfall")
        complete.text = "mutated"
        assembly.sections.append({"name": "late", "text": "late"})
        return await next_fn()

    ctx.on("system-prompt/assemble", mutator, prepend=True)

    res = await ctx.systemPrompt.assemble()
    assert res.sections == [{"name": "complete", "text": "Exact prompt."}]


@pytest.mark.asyncio
async def test_rejects_multiple_effective_complete_sections():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    ctx.systemPrompt.section({"name": "first", "order": 10, "text": "first", "complete": True})
    ctx.systemPrompt.section({"name": "second", "order": 20, "text": "second", "complete": True})

    with pytest.raises(Exception, match='multiple complete prompt sections are active: "first", "second"'):
        await ctx.systemPrompt.assemble()


@pytest.mark.asyncio
async def test_assembles_snapshots_so_one_step_mutations_do_not_leak():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    ctx.systemPrompt.section({"name": "base", "order": 10, "text": "base"})
    ctx.systemPrompt.tools(
        lambda c=None: {
            "schemas": [
                {
                    "name": "t",
                    "description": "tool",
                    "parameters": {"type": "object", "properties": {}},
                }
            ]
        }
    )

    first = await ctx.systemPrompt.assemble()
    first.sections[0].name = "mutated"
    first.sections[0].text = "mutated"
    first.contexts.append({"name": "mutated", "text": "mutated"})
    first.tools[0].description = "mutated"
    first.tools[0].parameters["properties"]["leak"] = {"type": "string"}

    second = await ctx.systemPrompt.assemble()
    assert [s.name for s in second.sections] == ["harness:identity", "deployment:persona", "base"]
    assert second.sections[0].text == IDENTITY
    assert second.contexts == []
    assert second.tools == [{"name": "t", "description": "tool", "parameters": {"type": "object", "properties": {}}}]


def test_filters_out_empty_section_text_from_render_prompt():
    result = render_prompt({
        "sections": [
            {"name": "empty", "text": ""},
            {"name": "real", "text": "content"},
        ],
        "contexts": [],
        "tools": [],
        "variables": {},
    })
    assert result == "content"


@pytest.mark.asyncio
async def test_filters_empty_context_interpolates_variables_and_returns_empty_without_active_context():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    ctx.systemPrompt.context({"name": "empty", "order": 0, "text": ""})
    assert render_context_snapshot(await ctx.systemPrompt.assemble()) == ""

    ctx.systemPrompt.variable("mode", lambda c=None: "read-only")
    ctx.systemPrompt.context({"name": "policy", "order": 1, "text": "Mode: {{mode}}."})
    assert render_context_snapshot(await ctx.systemPrompt.assemble()) == (
        "Current runtime context. This snapshot supersedes earlier runtime-context snapshots.\n\nMode: read-only."
    )


def test_attributes_context_interpolation_failures_to_contributing_context():
    with pytest.raises(
        Exception,
        match=r'unknown prompt variable "\{\{missing\}\}" in context "policy"; registered variables: \(none\)',
    ):
        render_context_snapshot({
            "sections": [],
            "contexts": [{"name": "policy", "text": "Mode: {{missing}}."}],
            "tools": [],
            "variables": {},
        })


@pytest.mark.asyncio
async def test_emits_change_when_tool_provider_registered_and_disposed():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    count = [0]
    ctx.on("system-prompt/change", lambda: count.__setitem__(0, count[0] + 1))

    dispose = ctx.systemPrompt.tools(lambda c=None: {"schemas": []})
    assert count[0] == 1

    dispose()
    assert count[0] == 2


@pytest.mark.asyncio
async def test_emits_change_when_context_registered_and_disposed():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    count = [0]
    ctx.on("system-prompt/change", lambda: count.__setitem__(0, count[0] + 1))

    dispose = ctx.systemPrompt.context({"name": "policy", "order": 0, "text": "current"})
    assert count[0] == 1

    dispose()
    assert count[0] == 2


@pytest.mark.asyncio
async def test_cleans_up_tool_providers_on_fiber_dispose():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    def fiber_plugin(inner: Context):
        inner.systemPrompt.tools(lambda c=None: {"schemas": [{"name": "fiber-tool", "description": "", "parameters": {}}]})

    fiber_plugin.inject = ["systemPrompt"]
    fiber = await ctx.plugin(fiber_plugin)

    assert len((await ctx.systemPrompt.assemble()).tools) == 1
    await fiber.dispose()
    assert len((await ctx.systemPrompt.assemble()).tools) == 0


@pytest.mark.asyncio
async def test_removes_section_when_returned_disposer_called_directly():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    dispose = ctx.systemPrompt.section({"name": "direct", "order": 0, "text": "direct section"})
    assert len(contributed(await ctx.systemPrompt.assemble())) == 1

    dispose()
    assert len(contributed(await ctx.systemPrompt.assemble())) == 0


@pytest.mark.asyncio
async def test_removes_tool_provider_when_returned_disposer_called_directly():
    ctx = Context()
    await ctx.plugin(SystemPrompt)

    dispose = ctx.systemPrompt.tools(lambda c=None: {"schemas": [{"name": "direct-tool", "description": "", "parameters": {}}]})
    assert len((await ctx.systemPrompt.assemble()).tools) == 1

    dispose()
    assert len((await ctx.systemPrompt.assemble()).tools) == 0


class TestPromptVariables:
    @pytest.mark.asyncio
    async def test_resolves_variable_against_assemble_context_and_emits_change(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt)

        count = [0]
        ctx.on("system-prompt/change", lambda: count.__setitem__(0, count[0] + 1))

        dispose = ctx.systemPrompt.variable(
            "who",
            lambda context: context.get("who") if isinstance(context, dict) else None,
        )
        assert count[0] == 1

        res1 = await ctx.systemPrompt.assemble({"who": "alice"})
        assert res1.variables == {"who": "alice"}

        res2 = await ctx.systemPrompt.assemble()
        assert res2.variables == {"who": None}

        dispose()
        assert count[0] == 2
        assert (await ctx.systemPrompt.assemble()).variables == {}

    @pytest.mark.asyncio
    async def test_live_iterates_variables_registered_by_earlier_provider(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        added = False

        def first_var(c=None):
            nonlocal added
            if not added:
                added = True
                ctx.systemPrompt.variable("late", lambda c2=None: "second value")
            return "first value"

        ctx.systemPrompt.variable("first", first_var)

        assert (await ctx.systemPrompt.assemble()).variables == {
            "first": "first value",
            "late": "second value",
        }

    @pytest.mark.asyncio
    async def test_rejects_duplicate_variable_name_and_unreferenceable_name(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        ctx.systemPrompt.variable("model", lambda c=None: "m1")

        with pytest.raises(Exception, match='prompt variable "model" is already registered'):
            ctx.systemPrompt.variable("model", lambda c=None: "m2")

        with pytest.raises(Exception, match='invalid prompt variable name "Not Valid"'):
            ctx.systemPrompt.variable("Not Valid", lambda c=None: "x")

        assert (await ctx.systemPrompt.assemble()).variables == {"model": "m1"}

    @pytest.mark.asyncio
    async def test_interpolates_references_in_section_text_at_render(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt, {"persona": "You run on {{model}} in {{cwd}}."})
        ctx.systemPrompt.variable("model", lambda c=None: "deepseek-v4")
        ctx.systemPrompt.variable("cwd", lambda c=None: "/work")

        assert render_prompt(await ctx.systemPrompt.assemble()) == f"{IDENTITY}\n\nYou run on deepseek-v4 in /work."

    @pytest.mark.asyncio
    async def test_lets_waterfall_listener_add_or_override_variables_before_render(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        ctx.systemPrompt.section({"name": "s", "order": 0, "text": "{{extra}}"})

        async def on_assemble(assembly, _context, next_fn):
            assembly.variables["extra"] = "from-waterfall"
            return await next_fn()

        ctx.on("system-prompt/assemble", on_assemble)
        assert render_prompt(await ctx.systemPrompt.assemble()) == f"{IDENTITY}\n\nfrom-waterfall"

    @pytest.mark.asyncio
    async def test_throws_on_reference_to_unregistered_variable(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        ctx.systemPrompt.section({"name": "persona", "order": 0, "text": "on {{modle}}"})
        ctx.systemPrompt.variable("model", lambda c=None: "m")

        assembly = await ctx.systemPrompt.assemble()
        with pytest.raises(
            Exception,
            match=r'unknown prompt variable "\{\{modle\}\}" in section "persona"; registered variables: model',
        ):
            render_prompt(assembly)

    def test_names_none_when_no_variables_registered(self):
        with pytest.raises(
            Exception,
            match=r'unknown prompt variable "\{\{x\}\}" in section "s"; registered variables: \(none\)',
        ):
            render_prompt({"sections": [{"name": "s", "text": "{{x}}"}], "contexts": [], "tools": [], "variables": {}})

    def test_throws_when_referenced_variable_has_no_value(self):
        with pytest.raises(
            Exception,
            match=r'prompt variable "\{\{cwd\}\}" has no value for this assembly \(section "persona"\)',
        ):
            render_prompt({
                "sections": [{"name": "persona", "text": "in {{cwd}}"}],
                "contexts": [],
                "tools": [],
                "variables": {"cwd": None},
            })

    def test_throws_on_malformed_complete_reference_e_g_inner_spaces(self):
        with pytest.raises(Exception, match=r'malformed prompt variable reference "\{\{ model \}\}" in section "s"'):
            render_prompt({
                "sections": [{"name": "s", "text": "on {{ model }}"}],
                "contexts": [],
                "tools": [],
                "variables": {"model": "m"},
            })

    def test_leaves_lone_verbatim_only_when_no_closing_braces_follow(self):
        text = render_prompt({
            "sections": [{"name": "s", "text": "shell ${X:-{{fallback} stays"}],
            "contexts": [],
            "tools": [],
            "variables": {},
        })
        assert text == "shell ${X:-{{fallback} stays"

    @pytest.mark.parametrize(
        "text,label",
        [
            ("{{{model}}}", "extra outer braces"),
            ("x {{a{b}} y {{model}}", "nested brace inside a would-be group"),
        ],
    )
    def test_throws_on_mangled_reference_with_closing_braces_following(self, text, label):
        with pytest.raises(Exception, match="malformed prompt variable reference at"):
            render_prompt({
                "sections": [{"name": "s", "text": text}],
                "contexts": [],
                "tools": [],
                "variables": {"model": "m"},
            })

    def test_rejects_constructor_as_unknown(self):
        with pytest.raises(Exception, match=r'unknown prompt variable "\{\{constructor\}\}"'):
            render_prompt({
                "sections": [{"name": "s", "text": "on {{constructor}}"}],
                "contexts": [],
                "tools": [],
                "variables": {"model": "m"},
            })

    @pytest.mark.asyncio
    async def test_variable_named_like_prototype_property_works_when_registered(self):
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        ctx.systemPrompt.section({"name": "s", "order": 0, "text": "{{constructor}}"})
        ctx.systemPrompt.variable("constructor", lambda c=None: "own-value")
        assert render_prompt(await ctx.systemPrompt.assemble()) == f"{IDENTITY}\n\nown-value"

    def test_never_rescans_substituted_values(self):
        text = render_prompt({
            "sections": [{"name": "s", "text": "v = {{model}}!"}],
            "contexts": [],
            "tools": [],
            "variables": {"model": "literal {{sneaky}} inside"},
        })
        assert text == "v = literal {{sneaky}} inside!"
