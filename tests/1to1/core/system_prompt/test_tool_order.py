"""
1:1 port of reference/packages/core/system-prompt/tests/tool-order.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, List, Optional
import pytest

from dsh.cordis.context import Context
from dsh.core.system_prompt import SystemPrompt, TOOL_ORDER_REST


def tool(name: str, description: Optional[str] = None) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description if description is not None else name,
        "parameters": {"type": "object", "properties": {}},
    }


def mount(config: Optional[Dict[str, Any]] = None) -> Context:
    ctx = Context()
    ctx.plugin(SystemPrompt, config or {})
    return ctx


def names(assembly: Dict[str, Any]) -> List[str]:
    return [t["name"] for t in assembly.get("tools", [])]


def test_exports_the_rest_entry_as_unlisted_tools():
    assert TOOL_ORDER_REST == "<unlisted-tools>"


@pytest.mark.asyncio
async def test_assembles_tools_in_lexicographic_name_order_when_no_tool_order():
    ctx = mount()
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.tools(lambda _: {"schemas": [tool("charlie"), tool("alpha")]})
    sp.tools(lambda _: {"schemas": [tool("bravo")]})
    assembly = await sp.assemble()
    assert names(assembly) == ["alpha", "bravo", "charlie"]


@pytest.mark.asyncio
async def test_assembles_the_same_order_regardless_of_provider_registration_order():
    forward = mount()
    sp_f: SystemPrompt = forward.get("systemPrompt")
    sp_f.tools(lambda _: {"schemas": [tool("alpha")]})
    sp_f.tools(lambda _: {"schemas": [tool("zulu")]})

    backward = mount()
    sp_b: SystemPrompt = backward.get("systemPrompt")
    sp_b.tools(lambda _: {"schemas": [tool("zulu")]})
    sp_b.tools(lambda _: {"schemas": [tool("alpha")]})

    assert names(await sp_f.assemble()) == ["alpha", "zulu"]
    assert names(await sp_b.assemble()) == ["alpha", "zulu"]


@pytest.mark.asyncio
async def test_applies_a_configured_tool_order():
    ctx = mount({"toolOrder": ["todo_write", TOOL_ORDER_REST, "bash"]})
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.tools(lambda _: {"schemas": [tool("bash"), tool("echo_b"), tool("todo_write"), tool("echo_a")]})
    assembly = await sp.assemble()
    assert names(assembly) == ["todo_write", "echo_a", "echo_b", "bash"]


@pytest.mark.asyncio
async def test_rejects_assembly_when_tool_order_names_unregistered_tool():
    ctx = mount({"toolOrder": ["todo_write", "ghost", TOOL_ORDER_REST, "wraith"]})
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.tools(lambda _: {"schemas": [tool("bash"), tool("todo_write")]})
    with pytest.raises(ValueError, match=r'toolOrder lists unregistered tools "ghost", "wraith"; known tools: bash, todo_write'):
        await sp.assemble()


@pytest.mark.asyncio
async def test_names_single_unregistered_tool_when_no_tools_registered():
    ctx = mount({"toolOrder": ["ghost", TOOL_ORDER_REST]})
    sp: SystemPrompt = ctx.get("systemPrompt")
    with pytest.raises(ValueError, match=r'toolOrder lists unregistered tool "ghost"; known tools: \(none\)'):
        await sp.assemble()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_order", [None, [TOOL_ORDER_REST]])
async def test_rejects_provider_tool_named_like_reserved_rest_entry(tool_order):
    ctx = mount({} if tool_order is None else {"toolOrder": tool_order})
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.tools(lambda _: {"schemas": [tool(TOOL_ORDER_REST)]})
    with pytest.raises(ValueError, match=rf'tool provider returned reserved tool name "{TOOL_ORDER_REST}"'):
        await sp.assemble()


@pytest.mark.asyncio
async def test_keeps_collection_order_between_tools_that_share_name():
    ctx = mount()
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.tools(lambda _: {"schemas": [tool("dup", "first"), tool("anchor"), tool("dup", "second")]})
    assembly = await sp.assemble()
    assert [t["description"] for t in assembly["tools"]] == ["anchor", "first", "second"]


@pytest.mark.asyncio
async def test_canonicalizes_before_assemble_waterfall():
    ctx = mount()
    sp: SystemPrompt = ctx.get("systemPrompt")
    sp.tools(lambda _: {"schemas": [tool("zulu"), tool("alpha")]})
    seen: List[str] = []

    async def listener(assembly, _context, next_fn=None):
        seen.extend([t["name"] for t in assembly["tools"]])
        assembly["tools"].append(tool("aardvark"))
        return await next_fn() if next_fn else assembly

    ctx.on("system-prompt/assemble", listener)
    assembly = await sp.assemble()
    assert seen == ["alpha", "zulu"]
    assert names(assembly) == ["alpha", "zulu", "aardvark"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_order",
    [
        [],
        ["bash", "todo_write"],
    ],
)
async def test_rejects_missing_rest_entry_at_load(tool_order):
    ctx = Context()
    with pytest.raises(ValueError, match=rf'must contain the "{TOOL_ORDER_REST}" rest entry'):
        await ctx.plugin(SystemPrompt, {"toolOrder": tool_order})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_order",
    [
        ["bash", "bash", TOOL_ORDER_REST],
        [TOOL_ORDER_REST, "bash", TOOL_ORDER_REST],
    ],
)
async def test_rejects_duplicate_tool_name_at_load(tool_order):
    ctx = Context()
    with pytest.raises(ValueError, match=r"more than once"):
        await ctx.plugin(SystemPrompt, {"toolOrder": tool_order})


def test_throws_from_direct_construction():
    with pytest.raises(ValueError, match=r"rest entry"):
        SystemPrompt(Context(), {"toolOrder": ["bash"]})
