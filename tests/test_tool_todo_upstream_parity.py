import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.core.session import Session
from dsh.core.tools import ToolExecutionInput, ToolRunContext, ToolsService
from dsh.session.projections import SessionProjectionRegistry
from dsh.todo.tool_todo import ToolTodoPlugin, compose_todo_description


PRESET_ROOT = Path(__file__).resolve().parents[1] / "dsh" / "presets"


class _PresetLoader(yaml.SafeLoader):
    pass


_PresetLoader.add_constructor(
    "tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node),
)


def _context():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.provide("tools", tools)
    return ctx, tools


async def _mount(allow_parallel=True):
    ctx, tools = _context()
    config = {"allowParallelInProgress": allow_parallel}
    fiber = ctx.registry.plugin(
        ToolTodoPlugin(config=config), config=config, parent_ctx=ctx,
    )
    await fiber
    return ctx, tools, fiber


async def _execute(tools, todos, agent=... , session=None):
    if agent is ...:
        owned = Session.create("todo-owner")
        agent = SimpleNamespace(id="todo-owner", session=owned)
    execution = ToolExecutionInput(
        "todo-call", "todo_write", {"todos": todos}, agent=agent,
        session=session, signal=asyncio.Event(),
    )
    return await tools.execute(execution), agent


def test_shipped_todo_presets_explicitly_enable_parallel_in_progress():
    expected = {
        "standard.yaml",
        "standard/agent.cordis.yml",
        "creative.yaml",
        "creative/agent.cordis.yml",
        "cordis.yaml",
        "cordis/agent.cordis.yml",
        "code.yaml",
        "code/agent.cordis.yml",
    }
    candidates = list(PRESET_ROOT.glob("*.yaml"))
    candidates.extend(PRESET_ROOT.glob("*/agent.cordis.yml"))
    found = set()

    for path in candidates:
        rows = yaml.load(path.read_text(encoding="utf-8"), Loader=_PresetLoader)
        todo_rows = [row for row in rows or []
                     if row.get("name") == "@deepseek-ai/dsh-tool-todo"]
        assert len(todo_rows) <= 1, str(path)
        if not todo_rows:
            continue
        relative = path.relative_to(PRESET_ROOT).as_posix()
        found.add(relative)
        assert todo_rows[0].get("config") == {
            "allowParallelInProgress": True,
        }, relative

    assert found == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"allowParallelInProgress": "yes"}])
async def test_config_requires_an_explicit_boolean_policy(config):
    ctx, _tools = _context()
    fiber = ctx.registry.plugin(
        ToolTodoPlugin(config=config), config=config, parent_ctx=ctx,
    )

    with pytest.raises(TypeError, match="allowParallelInProgress"):
        await fiber


@pytest.mark.asyncio
async def test_loader_composition_rejects_a_non_boolean_policy():
    ctx, _tools = _context()
    loader = Loader(ctx)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-todo", ToolTodoPlugin)

    with pytest.raises(Exception, match="allowParallelInProgress expected boolean"):
        await loader.root.update([{
            "id": "todo",
            "name": "@deepseek-ai/dsh-tool-todo",
            "config": {"allowParallelInProgress": "yes"},
        }])


@pytest.mark.asyncio
async def test_registers_the_canonical_schema_output_and_presentation():
    _ctx, tools, _fiber = await _mount(True)
    tool = tools.get("todo_write")

    assert tool is not None
    assert tool.canonical is True
    assert list(tool.parameters["properties"]) == ["todos"]
    item = tool.parameters["properties"]["todos"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["content", "status"]
    assert item["properties"]["status"]["enum"] == [
        "pending", "in_progress", "completed",
    ]
    assert tool.output["schema"]["additionalProperties"] is False
    assert tool.present_call({"todos": [{"content": "a", "status": "pending"}]}) == {
        "card": "generic",
        "title": "Update todo list",
        "kind": "other",
        "rawInput": [{"content": "a", "status": "pending"}],
    }


@pytest.mark.asyncio
async def test_execute_uses_tool_run_context_agent_session_and_returns_value():
    _ctx, tools, _fiber = await _mount(True)
    seen = []
    tool = tools.get("todo_write")
    original = tool.handler

    async def inspect_exec(args, execution):
        seen.append(execution)
        return await original(args, execution)

    tool.handler = inspect_exec
    result, agent = await _execute(tools, [
        {"content": "  plan  ", "status": "in_progress"},
        {"content": "build", "status": "pending"},
        {"content": "verify", "status": "completed"},
    ])

    assert isinstance(seen[0], ToolRunContext)
    assert result.is_error is False
    assert result.value == {
        "todos": [
            {"content": "plan", "status": "in_progress"},
            {"content": "build", "status": "pending"},
            {"content": "verify", "status": "completed"},
        ],
        "counts": {"pending": 1, "inProgress": 1, "completed": 1},
    }
    assert result.content == [{
        "type": "text",
        "text": "Updated todo list: 1 pending, 1 in progress, 1 completed.",
    }]
    event = agent.session.events[-1]
    assert event["type"] == "todo/write"
    assert event["data"] == {"todos": list(result.value["todos"])}
    assert "ignorable" not in event


@pytest.mark.asyncio
async def test_non_agent_caller_is_rejected_even_with_a_session_carrier():
    _ctx, tools, _fiber = await _mount(True)
    fallback = Session.create("not-an-agent")
    result, _agent = await _execute(
        tools, [{"content": "a", "status": "pending"}],
        agent=None, session=fallback,
    )

    assert result.is_error is True
    assert "owning agent session" in result.content[0]["text"]
    assert fallback.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "todos, fragment",
    [
        ("nope", None),
        ([{"content": "a", "status": "doing"}], None),
        ([{"content": "a", "status": "pending", "children": []}], "not a declared property"),
        ([{"content": "   ", "status": "pending"}], "non-empty"),
        ([
            {"content": "same", "status": "pending"},
            {"content": "same", "status": "completed"},
        ], "duplicate content"),
    ],
)
async def test_invalid_inputs_fail_without_appending(todos, fragment):
    _ctx, tools, _fiber = await _mount(True)
    agent = SimpleNamespace(id="invalid", session=Session.create("invalid"))
    result, _ = await _execute(tools, todos, agent=agent)

    assert result.is_error is True
    if fragment is not None:
        assert fragment in result.content[0]["text"]
    assert agent.session.events == []


@pytest.mark.asyncio
async def test_parallel_policy_changes_description_and_validation():
    parallel = [
        {"content": "first", "status": "in_progress"},
        {"content": "second", "status": "in_progress"},
    ]
    _ctx, tools, _fiber = await _mount(False)
    result, agent = await _execute(tools, parallel)

    assert "AT MOST ONE" in tools.get("todo_write").description
    assert "several at once" not in tools.get("todo_write").description
    assert result.is_error is True
    assert "at most one task may be in_progress (got 2)" in result.content[0]["text"]
    assert agent.session.events == []
    assert "several at once" in compose_todo_description(True)


@pytest.mark.asyncio
async def test_projection_activates_late_folds_events_and_unloads_with_plugin():
    ctx, tools, fiber = await _mount(True)
    assert tools.get("todo_write") is not None

    projections = SessionProjectionRegistry(ctx)
    ctx.provide("sessionProjections", projections)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert projections.has("todos") is True
    unit = projections.get_unit("todos")
    assert unit.state_version == 2
    state = unit.init()
    todos = [{"content": "a", "status": "pending"}]
    state = unit.apply(state, {"type": "todo/write", "data": {"todos": todos}})
    assert state is todos
    assert unit.apply(state, {"type": "turn/end", "data": {}}) is state
    assert unit.apply(state, {"type": "turn/start", "data": {}}) is None

    await fiber.dispose()
    assert tools.get("todo_write") is None
    assert projections.has("todos") is False
