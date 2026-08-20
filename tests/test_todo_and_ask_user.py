import json
import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionStore
from dsh.core.tools import ToolsService
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

    ctx.plugin(ToolTodoPlugin)

    todos_payload = [
        {"content": "Implement feature A", "status": "completed"},
        {"content": "Implement feature B", "status": "in_progress"},
        {"content": "Write unit tests", "status": "pending"},
    ]

    res = await tools.execute_tool("todo_write", {"todos": todos_payload})
    assert "Updated todo list: 1 pending, 1 in progress, 1 completed." in res

    # Verify session log recorded todo/write event
    events = session.events
    todo_events = [e for e in events if e.get("type") == "todo/write"]
    assert len(todo_events) == 1
    assert todo_events[0]["data"]["todos"] == todos_payload


@pytest.mark.asyncio
async def test_ask_user_question_tool_execution():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    ctx.plugin(ToolAskUserPlugin)

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

    raw_res = await tools.execute_tool("ask_user_question", {"questions": questions_payload})
    data = json.loads(raw_res)
    assert "answers" in data
    assert len(data["answers"]) == 1
    assert data["answers"][0]["id"] == "q1"
    assert data["answers"][0]["selected"] == ["Cordis Plugin"]
