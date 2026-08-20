import asyncio
import json
import pytest
from dsh.cordis.context import Context
from dsh.core.session import SessionStore
from dsh.core.agent_loop import AgentLoopService
from dsh.goal.tool_goal import GoalService
from dsh.plan.plan_mode import PlanModeController
from dsh.host.webserver.webserver import WebServerService, WebServerPlugin, HttpResponseWriter
from dsh.host.directory_picker.directory_picker import DirectoryPickerAutoPlugin, NativeDirectoryPickerPlugin
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
    ctx.plugin(DirectoryPickerAutoPlugin)
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


@pytest.mark.asyncio
async def test_sse_agent_status_and_session_events(web_ctx):
    from dsh.core.agent import Agent
    from dsh.core.session import Session

    # Create dummy agent with session
    session = Session.create("default-session", ctx=web_ctx)
    agent = Agent(session=session, ctx=web_ctx)

    # Emit agent/status with Agent object in payload (must not crash)
    web_ctx.emit("agent/status", {"agent": agent, "status": "running"})
    web_ctx.emit("agent/status", {"agent": agent, "status": "idle"})

    # Emit session/event
    session.append_user_message("Hello from user")
    session.append_assistant_message({"content": "Hello! I am ready."})

    # Emit session/chunk
    web_ctx.emit("session/chunk", session, {"type": "assistant/chunk", "data": {"delta_type": "text", "delta": "Hello"}})

    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_api_advanced_endpoints(web_ctx):
    server: WebServerService = web_ctx.get("web_server")
    route = server.match("/api/workspace/files")

    class MockWriter:
        def __init__(self):
            self.data = bytearray()
        def write(self, b):
            self.data.extend(b)
        async def drain(self): pass
        def get_json(self):
            parts = self.data.split(b"\r\n\r\n", 1)
            return json.loads(parts[1].decode("utf-8")) if len(parts) > 1 else {}
        def write_header(self, k, v): pass
        def write_body(self, b): self.data.extend(b)
        async def finish(self): pass
        async def send_headers(self): pass

    # 1. /api/workspace/files
    req_files = {"method": "GET", "path": "/api/workspace/files", "query": "", "headers": {}, "body": b""}
    writer_files = MockWriter()
    await route.handler(req_files, HttpResponseWriter(writer_files))
    res_files = writer_files.get_json()
    assert "files" in res_files
    assert isinstance(res_files["files"], list)

    # 2. /api/settings/describe
    req_desc = {"method": "GET", "path": "/api/settings/describe", "query": "", "headers": {}, "body": b""}
    writer_desc = MockWriter()
    await route.handler(req_desc, HttpResponseWriter(writer_desc))
    res_desc = writer_desc.get_json()
    assert "llm" in res_desc
    assert "plugins" in res_desc

    # 3. /api/permission/set
    req_perm = {
        "method": "POST",
        "path": "/api/permission/set",
        "query": "",
        "headers": {},
        "body": json.dumps({"preset": "read-only"}).encode("utf-8"),
    }
    writer_perm = MockWriter()
    await route.handler(req_perm, HttpResponseWriter(writer_perm))
    res_perm = writer_perm.get_json()
    assert res_perm["success"] is True
    assert res_perm["preset"] == "read-only"

    # 4. /api/jobs/list
    req_jobs = {"method": "GET", "path": "/api/jobs/list", "query": "", "headers": {}, "body": b""}
    writer_jobs = MockWriter()
    await route.handler(req_jobs, HttpResponseWriter(writer_jobs))
    res_jobs = writer_jobs.get_json()
    assert "jobs" in res_jobs


@pytest.mark.asyncio
async def test_api_official_rpc_contract(web_ctx):
    server: WebServerService = web_ctx.get("web_server")
    route = server.match("/api/host.pickDirectory")
    assert route is not None

    dp = web_ctx.get("directory_picker")
    dp.pick_native = lambda: "C:/Projects/deepseek"

    class MockWriter:
        def __init__(self):
            self.data = bytearray()
        def write(self, b): self.data.extend(b)
        async def drain(self): pass
        def get_json(self):
            parts = self.data.split(b"\r\n\r\n", 1)
            return json.loads(parts[1].decode("utf-8")) if len(parts) > 1 else {}
        def write_header(self, k, v): pass
        def write_body(self, b): self.data.extend(b)
        async def finish(self): pass
        async def send_headers(self): pass

    # 1. Test POST /api/host.pickDirectory
    req_pick = {
        "method": "POST",
        "path": "/api/host.pickDirectory",
        "query": "",
        "headers": {},
        "body": json.dumps({
            "type": "client-request",
            "rpcId": "rpc-pick-1",
            "method": "host.pickDirectory",
            "payload": {},
        }).encode("utf-8"),
    }
    writer_pick = MockWriter()
    await route.handler(req_pick, HttpResponseWriter(writer_pick))
    res_pick = writer_pick.get_json()
    assert res_pick["type"] == "server-response"
    assert res_pick["rpcId"] == "rpc-pick-1"
    assert res_pick["result"]["ok"] is True
    assert res_pick["result"]["value"]["path"] == "C:/Projects/deepseek"

    # 2. Test POST /api/workspace.list
    req_ws = {
        "method": "POST",
        "path": "/api/workspace.list",
        "query": "",
        "headers": {},
        "body": json.dumps({
            "type": "client-request",
            "rpcId": "rpc-ws-1",
            "method": "workspace.list",
            "payload": {},
        }).encode("utf-8"),
    }
    writer_ws = MockWriter()
    await route.handler(req_ws, HttpResponseWriter(writer_ws))
    res_ws = writer_ws.get_json()
    assert res_ws["type"] == "server-response"
    assert res_ws["result"]["ok"] is True
    assert "items" in res_ws["result"]["value"]

    # 3. Test POST /api/workspace.create
    req_ws_create = {
        "method": "POST",
        "path": "/api/workspace.create",
        "query": "",
        "headers": {},
        "body": json.dumps({
            "type": "client-request",
            "rpcId": "rpc-ws-create-1",
            "method": "workspace.create",
            "payload": {"path": "C:/Projects/test-ws"},
        }).encode("utf-8"),
    }
    writer_ws_create = MockWriter()
    await route.handler(req_ws_create, HttpResponseWriter(writer_ws_create))
    res_ws_create = writer_ws_create.get_json()
    assert res_ws_create["type"] == "server-response"
    assert res_ws_create["result"]["ok"] is True
    ws_view = res_ws_create["result"]["value"]["workspace"]
    assert ws_view["path"] == "C:/Projects/test-ws"
    assert len(ws_view["sessionIds"]) >= 1

    # 4. Test POST /api/session.create with workspaceId
    req_session_create = {
        "method": "POST",
        "path": "/api/session.create",
        "query": "",
        "headers": {},
        "body": json.dumps({
            "type": "client-request",
            "rpcId": "rpc-sess-create-1",
            "method": "session.create",
            "payload": {"workspaceId": ws_view["workspaceId"]},
        }).encode("utf-8"),
    }
    writer_sess_create = MockWriter()
    await route.handler(req_session_create, HttpResponseWriter(writer_sess_create))
    res_sess_create = writer_sess_create.get_json()
    assert res_sess_create["type"] == "server-response"
    assert res_sess_create["result"]["ok"] is True
    new_sid = res_sess_create["result"]["value"]["sessionId"]

    # 5. Verify workspace list has the new session attached
    writer_ws_2 = MockWriter()
    await route.handler(req_ws, HttpResponseWriter(writer_ws_2))
    res_ws_2 = writer_ws_2.get_json()
    matched_ws = [w for w in res_ws_2["result"]["value"]["items"] if w["workspaceId"] == ws_view["workspaceId"]][0]
    assert new_sid in matched_ws["sessionIds"]
