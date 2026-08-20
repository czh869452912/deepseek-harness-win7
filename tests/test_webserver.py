import asyncio
import json
import pytest
from dsh.cordis.context import Context
from dsh.core.session import SessionStore
from dsh.core.agent_loop import AgentLoopService
from dsh.goal.tool_goal import GoalService
from dsh.plan.plan_mode import PlanModeController
from dsh.host.webserver.webserver import WebServerService, WebServerPlugin, HttpResponseWriter
from dsh.host.frontend_static.frontend_static import FrontendStaticPlugin
from dsh.host.apiproxy.api_proxy import ApiProxyPlugin


@pytest.fixture
def web_ctx():
    ctx = Context()
    sessions = SessionStore(ctx)
    ctx.set_service("sessions", sessions)
    sessions.create("default-session")
    agent_loop = AgentLoopService(ctx)
    ctx.set_service("agent_loop", agent_loop)
    goals = GoalService(ctx)
    ctx.set_service("goals", goals)
    plan_mode = PlanModeController(ctx)
    ctx.set_service("plan_mode", plan_mode)

    server_svc = WebServerService(ctx, host="127.0.0.1", port=0)
    ctx.set_service("web_server", server_svc)
    ctx.plugin(ApiProxyPlugin)
    ctx.plugin(FrontendStaticPlugin)
    return ctx


def test_webserver_route_matching(web_ctx):
    server: WebServerService = web_ctx.get("web_server")

    # Match /api prefix
    route = server.match("/api/status")
    assert route is not None
    assert route.path == "/api"
    assert route.kind == "prefix"

    # Match exact
    server.register("exact", "/health", lambda req, res: None)
    assert server.match("/health").kind == "exact"


@pytest.mark.asyncio
async def test_api_status_and_presets(web_ctx):
    server: WebServerService = web_ctx.get("web_server")
    route = server.match("/api/status")
    assert route is not None

    class MockWriter:
        def __init__(self):
            self.data = bytearray()
        def write(self, b):
            self.data.extend(b)
        async def drain(self):
            pass
        def get_json(self):
            parts = self.data.split(b"\r\n\r\n", 1)
            return json.loads(parts[1].decode("utf-8")) if len(parts) > 1 else {}
        def write_header(self, k, v): pass
        def write_body(self, b): self.data.extend(b)
        async def finish(self): pass
        async def send_headers(self): pass

    # Test /api/status
    req_status = {"method": "GET", "path": "/api/status", "query": "", "headers": {}, "body": b""}
    writer = MockWriter()
    await route.handler(req_status, HttpResponseWriter(writer))
    resp = writer.get_json()
    assert resp["status"] == "ready"
    assert "planMode" in resp

    # Test /api/presets/list
    req_presets = {"method": "GET", "path": "/api/presets/list", "query": "", "headers": {}, "body": b""}
    writer_presets = MockWriter()
    await route.handler(req_presets, HttpResponseWriter(writer_presets))
    presets_resp = writer_presets.get_json()
    assert "presets" in presets_resp
    preset_ids = [p["id"] for p in presets_resp["presets"]]
    assert "standard" in preset_ids
    assert "minimal" in preset_ids
    assert "creative" in preset_ids


@pytest.mark.asyncio
async def test_api_plan_and_goal_actions(web_ctx):
    server: WebServerService = web_ctx.get("web_server")
    route = server.match("/api/plan/set")
    plan_mode: PlanModeController = web_ctx.get("plan_mode")

    class MockWriter:
        def __init__(self):
            self.data = bytearray()
        def write(self, b):
            self.data.extend(b)
        async def drain(self):
            pass
        def get_json(self):
            parts = self.data.split(b"\r\n\r\n", 1)
            return json.loads(parts[1].decode("utf-8")) if len(parts) > 1 else {}
        def write_header(self, k, v): pass
        def write_body(self, b): self.data.extend(b)
        async def finish(self): pass
        async def send_headers(self): pass

    # Set plan mode
    req_plan = {
        "method": "POST",
        "path": "/api/plan/set",
        "query": "",
        "headers": {},
        "body": json.dumps({"active": True}).encode("utf-8"),
    }
    writer = MockWriter()
    await route.handler(req_plan, HttpResponseWriter(writer))
    assert plan_mode.is_active() is True

    # Goal action
    req_goal = {
        "method": "POST",
        "path": "/api/goal/action",
        "query": "",
        "headers": {},
        "body": json.dumps({"action": "create", "objective": "Test Web GUI"}).encode("utf-8"),
    }
    writer_goal = MockWriter()
    await route.handler(req_goal, HttpResponseWriter(writer_goal))
    res_goal = writer_goal.get_json()
    assert res_goal["success"] is True
    assert res_goal["goal"]["objective"] == "Test Web GUI"


@pytest.mark.asyncio
async def test_api_model_settings_and_fork(web_ctx):
    server: WebServerService = web_ctx.get("web_server")
    route = server.match("/api/model/set")

    class MockWriter:
        def __init__(self):
            self.data = bytearray()
        def write(self, b):
            self.data.extend(b)
        async def drain(self):
            pass
        def get_json(self):
            parts = self.data.split(b"\r\n\r\n", 1)
            return json.loads(parts[1].decode("utf-8")) if len(parts) > 1 else {}
        def write_header(self, k, v): pass
        def write_body(self, b): self.data.extend(b)
        async def finish(self): pass
        async def send_headers(self): pass

    # 1. Model Set
    req_model = {
        "method": "POST",
        "path": "/api/model/set",
        "query": "",
        "headers": {},
        "body": json.dumps({"model": "deepseek-reasoner"}).encode("utf-8"),
    }
    writer = MockWriter()
    await route.handler(req_model, HttpResponseWriter(writer))
    res = writer.get_json()
    assert res["success"] is True
    assert res["model"] == "deepseek-reasoner"

    # 2. Settings Save
    req_settings = {
        "method": "POST",
        "path": "/api/settings/save",
        "query": "",
        "headers": {},
        "body": json.dumps({
            "baseUrl": "https://api.deepseek.com/v1",
            "apiKey": "sk-test",
            "model": "deepseek-v4-flash",
        }).encode("utf-8"),
    }
    writer_settings = MockWriter()
    await route.handler(req_settings, HttpResponseWriter(writer_settings))
    assert writer_settings.get_json()["success"] is True

    # 3. Session Fork
    req_fork = {
        "method": "POST",
        "path": "/api/session/fork",
        "query": "",
        "headers": {},
        "body": json.dumps({
            "sourceSessionId": "default-session",
            "newSessionId": "forked-session-1",
        }).encode("utf-8"),
    }
    writer_fork = MockWriter()
    await route.handler(req_fork, HttpResponseWriter(writer_fork))
    fork_res = writer_fork.get_json()
    assert fork_res["success"] is True
    assert fork_res["sessionId"] == "forked-session-1"
