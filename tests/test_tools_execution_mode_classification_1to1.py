"""
Tests for fail-closed per-call tool concurrency classification and model-schema isolation
matching reference/packages/core/tools/tests/execution-mode.spec.ts.
"""

import pytest
from dsh.cordis.context import Context
from dsh.core.tools import Tool, ToolsService, ToolExecutionInput


def test_tool_execution_mode_parallel_only_for_explicit_true():
    """Returns parallel only for an explicit true classifier."""
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    tools.register(
        name="safe",
        description="parallel-safe",
        parameters={},
        handler=lambda: "ok",
        is_concurrency_safe=lambda args: True,
    )

    inp = ToolExecutionInput(call_id="c1", name="safe", arguments={})
    assert tools.execution_mode(inp) == {"kind": "parallel"}


def test_tool_execution_mode_defaults_to_exclusive():
    """Defaults to exclusive for a tool with no isConcurrencySafe declaration."""
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    tools.register(
        name="plain",
        description="no declaration",
        parameters={},
        handler=lambda: "ok",
    )

    inp = ToolExecutionInput(call_id="c1", name="plain", arguments={})
    assert tools.execution_mode(inp) == {"kind": "exclusive"}


def test_tool_execution_mode_unknown_tool():
    """Returns exclusive for an unknown tool."""
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    inp = ToolExecutionInput(call_id="c1", name="nonexistent", arguments={})
    assert tools.execution_mode(inp) == {"kind": "exclusive"}


def test_tool_execution_mode_dynamic_args_classifier():
    """Returns parallel only when classifier returns true for the given arguments."""
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    tools.register(
        name="rw_tool",
        description="read or write",
        parameters={"mode": {"type": "string"}},
        handler=lambda mode: mode,
        is_concurrency_safe=lambda args: args.get("mode") == "read",
    )

    inp_read = ToolExecutionInput(call_id="c1", name="rw_tool", arguments={"mode": "read"})
    inp_write = ToolExecutionInput(call_id="c2", name="rw_tool", arguments={"mode": "write"})

    assert tools.execution_mode(inp_read) == {"kind": "parallel"}
    assert tools.execution_mode(inp_write) == {"kind": "exclusive"}


def test_tool_execution_mode_throwing_classifier_fails_closed():
    """Treats a throwing classifier as exclusive (fail-closed)."""
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    def throwing_classifier(args):
        raise RuntimeError("classifier boom")

    tools.register(
        name="thrower",
        description="classifier throws",
        parameters={},
        handler=lambda: "ok",
        is_concurrency_safe=throwing_classifier,
    )

    inp = ToolExecutionInput(call_id="c1", name="thrower", arguments={})
    assert tools.execution_mode(inp) == {"kind": "exclusive"}


def test_is_concurrency_safe_never_reaches_schemas_projection():
    """isConcurrencySafe is an execution-layer concept and never leaks into LLM schemas."""
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    tools.register(
        name="safe_tool",
        description="safe",
        parameters={"x": {"type": "string"}},
        handler=lambda x: x,
        is_concurrency_safe=lambda args: True,
    )

    schemas = tools.get_tools()
    assert len(schemas) == 1
    schema = schemas[0]
    assert set(schema.keys()) == {"name", "description", "parameters"}
    assert "isConcurrencySafe" not in schema
    assert "is_concurrency_safe" not in schema
