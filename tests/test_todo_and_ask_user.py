import json
import asyncio
from types import SimpleNamespace
import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionStore
from dsh.core.tools import ToolExecutionInput, ToolsService
from dsh.interaction.tool_ask_user import ToolAskUserPlugin
from dsh.todo.tool_todo import ToolTodoPlugin


@pytest.mark.asyncio
async def test_todo_write_tool_execution():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    store = SessionStore(ctx=ctx)
    ctx.set_service("sessions", store)
    session = store.create("default-session")

    config = {"allowParallelInProgress": True}
    fiber = ctx.registry.plugin(
        ToolTodoPlugin, config=config, parent_ctx=ctx,
    )
    await fiber
    tools = fiber.ctx.tools

    todos_payload = [
        {"content": "Implement feature A", "status": "completed"},
        {"content": "Implement feature B", "status": "in_progress"},
        {"content": "Write unit tests", "status": "pending"},
    ]

    todo_tool = tools.get_tool("todo_write", fiber.ctx)
    assert todo_tool is not None
    text = await todo_tool.execute(
        {"todos": todos_payload},
        SimpleNamespace(agent=SimpleNamespace(id=session.id, session=session), signal=asyncio.Event()),
    )
    assert text["counts"] == {"pending": 1, "inProgress": 1, "completed": 1}

    # Verify session log recorded todo/write event
    events = session.events
    todo_events = [e for e in events if e.get("type") == "todo/write"]
    assert len(todo_events) == 1
    assert todo_events[0]["data"]["todos"] == todos_payload
    await fiber.dispose()


@pytest.mark.asyncio
async def test_ask_user_question_tool_execution():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    fiber = await ctx.registry.plugin(ToolAskUserPlugin, parent_ctx=ctx)
    tools = fiber.ctx.get("tools")

    questions_payload = [
        {
            "id": "q1",
            "question": "Which architecture pattern to use?",
            "options": [
                {"label": "Cordis Plugin", "description": "Recommended plugin pattern"},
                {"label": "Monolithic", "description": "Single module"},
            ],
        }
    ]

    result = await tools.execute(ToolExecutionInput(
        "ask-call", "ask_user_question", {"questions": questions_payload},
        agent=SimpleNamespace(ctx=fiber.ctx, id="test-agent"), signal=asyncio.Event()))
    raw_res = "".join(block.get("text", "") for block in result.content)
    data = json.loads(raw_res)
    assert "answers" in data
    assert len(data["answers"]) == 1
    assert data["answers"][0]["id"] == "q1"
    assert data["answers"][0]["selected"] == ["Cordis Plugin"]
