import asyncio
import json
import pytest
from dsh.cordis.context import Context
from dsh.core.session import SessionStore, SessionPlugin
from dsh.host.apiproxy.api_proxy import ApiProxyPlugin, format_sse_frame
from dsh.host.apiproxy.fetch_handler import normalize_rpc_method
from dsh.host.webserver.webserver import WebServerPlugin, HttpResponseWriter


def test_normalize_rpc_method():
    assert normalize_rpc_method("/api/session/list") == "session/list"
    assert normalize_rpc_method("/api/session.history") == "session.history"
    assert normalize_rpc_method("/api/workspace/create") == "workspace/create"
    assert normalize_rpc_method("/api/settings/describe") == "settings/describe"
    assert normalize_rpc_method("/api/llm/models") == "llm/models"


def test_format_sse_frame():
    frame = {"type": "session/event", "sessionId": "s-1", "data": {"hello": "world"}}
    sse = format_sse_frame(frame, rpc_id="rpc-100")
    assert isinstance(sse, bytes)
    sse_text = sse.decode("utf-8")
    assert "event: session/event\n" in sse_text or "data: " in sse_text
    assert "s-1" in sse_text
    assert "rpc-100" in sse_text


@pytest.fixture
def api_ctx():
    ctx = Context()
    sess_plugin = SessionPlugin()
    sess_plugin.apply(ctx)
    web_plugin = WebServerPlugin({"port": 0})
    web_plugin.apply(ctx)
    api_plugin = ApiProxyPlugin()
    api_plugin.apply(ctx)
    return ctx


@pytest.mark.asyncio
async def test_api_proxy_broadcast_and_routes(api_ctx):
    ctx = api_ctx
    api_proxy: ApiProxyPlugin = ctx.get("apiProxy")
    assert api_proxy is not None
    assert api_proxy.sessions_handler is not None
    assert api_proxy.workspace_handler is not None
    assert api_proxy.settings_handler is not None

    # Test client queue broadcast
    q = asyncio.Queue()
    api_proxy._mux_clients.append(q)
    await api_proxy._broadcast_mux({"type": "test/event", "content": "broadcast ok"})
    msg = await asyncio.wait_for(q.get(), timeout=2.0)
    assert isinstance(msg, bytes)
    msg_text = msg.decode("utf-8")
    assert "test/event" in msg_text
    assert "broadcast ok" in msg_text