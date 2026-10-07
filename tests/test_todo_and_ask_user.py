import json
import asyncio
from types import SimpleNamespace
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import Session, SessionStore, SessionPlugin
from dsh.core.tools import ToolExecutionInput, ToolsService
from dsh.interaction.tool_ask_user import ToolAskUserPlugin
from dsh.interaction.user_questions import UserQuestionsPlugin
from dsh.todo.tool_todo import ToolTodoPlugin


@pytest.mark.asyncio
async def test_todo_write_tool_execution():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    store = SessionStore(ctx=ctx)
    ctx.set_service("sessions", store)
    session = store.create("default-session")
    from dsh.core.agent import Agent, AgentPlugin
    AgentPlugin().apply(ctx)
    agent = Agent(session=session, ctx=ctx, agent_id="default-session")
    ctx.get("agents").enter(agent)

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

    await ctx.plugin(UserQuestionsPlugin)
    ctx.on('user-questions/request', lambda request, next_fn=None: {
        'answers': [{'id': question['id'], 'selected': ['Cordis Plugin']} for question in request['questions']]})

    fiber = await ctx.registry.plugin(ToolAskUserPlugin, parent_ctx=ctx)
    tools = fiber.ctx.get("tools")
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(AgentPlugin)
    agent = Agent(session=ctx.get('sessions').create('test-agent'), ctx=fiber.ctx, agent_id='test-agent')
    ctx.get('agents').enter(agent)

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
        agent=agent, signal=asyncio.Event()))
    assert not result.is_error, result.error
    raw_res = "".join(block.get("text", "") for block in result.content)
    data = json.loads(raw_res)
    assert "answers" in data
    assert len(data["answers"]) == 1
    assert data["answers"][0]["id"] == "q1"
    assert data["answers"][0]["selected"] == ["Cordis Plugin"]
    assert result.value == data
    await ctx.fiber.dispose()
