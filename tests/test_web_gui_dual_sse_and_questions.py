"""
Tests for Dual SSE streams (/api/events/mux & /api/events/host),
RPC endpoints (/api/respond, /api/agent/..., GET/POST /api/settings, /api/models, /api/sessions),
and Web UI question submission flow without freezing.
"""

import asyncio
import json
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.host.webserver.webserver import WebServerPlugin, WebServerService, HttpResponseWriter
from dsh.host.apiproxy.api_proxy import ApiProxyPlugin
from dsh.interaction.user_questions import UserQuestionService, UserQuestionsPlugin
from dsh.interaction.tool_ask_user import ToolAskUserPlugin


class MockWriter:
    def __init__(self):
        self.data = bytearray()
        self.chunks = []
        self._headers_sent = False

    def write(self, b):
        self.data.extend(b)

    async def drain(self):
        pass

    def write_header(self, k, v):
        pass

    def write_body(self, b):
        self.data.extend(b)

    async def write_chunk(self, b):
        self.chunks.append(b)
        self.data.extend(b)

    async def finish(self):
        pass

    async def send_headers(self):
        self._headers_sent = True

    def get_json(self):
        parts = self.data.split(b"\r\n\r\n", 1)
        if len(parts) > 1:
            return json.loads(parts[1].decode("utf-8"))
        return json.loads(self.data.decode("utf-8"))


@pytest.mark.asyncio
async def test_dual_sse_streams_endpoint_resolution():
    """Verify dual SSE stream routes /api/events/mux and /api/events/host resolve correctly."""
    ctx = Context()
    web_server = WebServerPlugin({"port": 0})
    api_proxy = ApiProxyPlugin()

    await ctx.registry.plugin(web_server, parent_ctx=ctx)
    await ctx.registry.plugin(api_proxy, parent_ctx=ctx)

    server: WebServerService = ctx.get("web_server")
    assert server.match("/api/events/mux") is not None
    assert server.match("/api/events.mux") is not None
    assert server.match("/api/events/host") is not None


@pytest.mark.asyncio
async def test_session_event_projects_tool_presenter_view():
    """Mux tool events expose transient presenter views per the TS contract."""
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    tools.register_legacy({
        "name": "demo_tool",
        "description": "demo",
        "parameters": {"type": "object", "properties": {}},
        "handler": lambda **kwargs: {"ok": True},
        "presentCall": lambda args: {"kind": "call", "title": "Demo"},
        "presentResult": lambda args, result: {"kind": "result", "ok": True},
    })
    api = ApiProxyPlugin()
    api.ctx = ctx
    call_view = api._tool_event_view({"type": "tool/call", "data": {"name": "demo_tool", "args": {}}})
    result_view = api._tool_event_view({"type": "tool/result", "data": {"name": "demo_tool", "args": {}, "result": {"ok": True}}})
    assert call_view == {"for": "call", "view": {"kind": "call", "title": "Demo"}}
    assert result_view == {"for": "result", "view": {"kind": "result", "ok": True}}


@pytest.mark.asyncio
async def test_get_post_settings_models_sessions_rpc_endpoints():
    """Verify GET and POST routes for /api/settings, /api/models, /api/sessions, and /api/agent/..."""
    ctx = Context()
    web_server = WebServerPlugin({"port": 0})
    api_proxy = ApiProxyPlugin()

    await ctx.registry.plugin(web_server, parent_ctx=ctx)
    await ctx.registry.plugin(api_proxy, parent_ctx=ctx)

    server: WebServerService = ctx.get("web_server")
    route = server.match("/api/settings")
    assert route is not None

    # 1. GET /api/settings
    req_get_settings = {
        "method": "GET",
        "path": "/api/settings",
        "query": "",
        "headers": {},
        "body": b"",
    }
    w1 = MockWriter()
    await route.handler(req_get_settings, HttpResponseWriter(w1))
    res1 = w1.get_json()
    assert "namespaces" in res1

    # 2. GET /api/models
    req_get_models = {
        "method": "GET",
        "path": "/api/models",
        "query": "",
        "headers": {},
        "body": b"",
    }
    w2 = MockWriter()
    await route.handler(req_get_models, HttpResponseWriter(w2))
    res2 = w2.get_json()
    assert "current" in res2 or "groups" in res2

    # 3. GET /api/sessions
    req_get_sessions = {
        "method": "GET",
        "path": "/api/sessions",
        "query": "",
        "headers": {},
        "body": b"",
    }
    w3 = MockWriter()
    await route.handler(req_get_sessions, HttpResponseWriter(w3))
    res3 = w3.get_json()
    assert "items" in res3

    # 4. POST /api/agent/list
    req_agent_list = {
        "method": "POST",
        "path": "/api/agent/list",
        "query": "",
        "headers": {},
        "body": json.dumps({
            "type": "client-request",
            "rpcId": "rpc-preset-1",
            "method": "agentPreset.list",
            "payload": {},
        }).encode("utf-8"),
    }
    w4 = MockWriter()
    await route.handler(req_agent_list, HttpResponseWriter(w4))
    res4 = w4.get_json()
    assert res4["type"] == "server-response"
    assert res4["result"]["ok"] is True
    assert "presets" in res4["result"]["value"]


@pytest.mark.asyncio
async def test_web_ui_question_submission_and_respond():
    """Verify that asking user a question creates pending request, sends SSE frame, and responds via POST /api/respond."""
    ctx = Context()
    web_server = WebServerPlugin({"port": 0})
    api_proxy = ApiProxyPlugin()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)

    await ctx.registry.plugin(web_server, parent_ctx=ctx)
    await ctx.registry.plugin(api_proxy, parent_ctx=ctx)
    ask_fiber = await ctx.registry.plugin(ToolAskUserPlugin, parent_ctx=ctx)
    tools = ask_fiber.ctx.get("tools")

    user_questions: UserQuestionService = ctx.get("userQuestions")
    assert user_questions is not None
    assert user_questions.provider is not None

    server: WebServerService = ctx.get("web_server")
    route = server.match("/api/respond")
    assert route is not None

    questions_arg = [
        {
            "id": "q1",
            "question": "Which mode to run?",
            "options": [{"label": "Fast"}, {"label": "Slow"}],
        }
    ]

    # Run ask_user_question in task
    from dsh.core.tools import ToolExecutionInput
    from types import SimpleNamespace
    tool = tools.get_tool("ask_user_question", ask_fiber.ctx)
    task = asyncio.create_task(tool.handler(
        {"questions": questions_arg},
        ToolExecutionInput("ask-call", "ask_user_question", {"questions": questions_arg}, signal=asyncio.Event()),
    ))

    await asyncio.sleep(0.05)

    # Check pending question in ApiProxy
    pending = api_proxy._pending_server_requests
    assert len(pending) == 1
    q_rpc_id = list(pending.keys())[0]
    assert pending[q_rpc_id]["type"] == "question"

    # Simulate Web UI sending POST /api/respond
    respond_body = {
        "type": "client-response",
        "rpcId": q_rpc_id,
        "result": {
            "ok": True,
            "value": {
                "sessionId": "default-session",
                "answer": {
                    "answers": [
                        {"id": "q1", "selected": ["Fast"], "custom": None}
                    ]
                }
            }
        }
    }

    req_respond = {
        "method": "POST",
        "path": "/api/respond",
        "query": "",
        "headers": {},
        "body": json.dumps(respond_body).encode("utf-8"),
    }
    w_resp = MockWriter()
    await route.handler(req_respond, HttpResponseWriter(w_resp))
    res_resp = w_resp.get_json()
    assert res_resp["accepted"] is True

    # Ensure task completes without freeze
    raw_ans = await asyncio.wait_for(task, timeout=2.0)
    ans_data = json.loads(raw_ans)
    assert ans_data["answers"][0]["id"] == "q1"
    assert ans_data["answers"][0]["selected"] == ["Fast"]
