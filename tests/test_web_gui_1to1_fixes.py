"""
Regression unit tests verifying 1:1 fixes for Web GUI plugin inventory status, agent presets, session management, and SSE streaming event targets.
"""

import asyncio
import json
import pytest
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.plugin import Plugin
from dsh.core.agent import Agent
from dsh.core.session import Session, SessionStore
from dsh.host.apiproxy.api_proxy import ApiProxyPlugin
from dsh.host.plugin_inventory.plugin_inventory import PluginInventoryGateway, PluginInventoryPlugin
from dsh.host.webserver.webserver import WebServerPlugin


class SamplePlugin(Plugin):
    id = "sample-plugin"
    name = "@deepseek-ai/dsh-sample-plugin"


@pytest.mark.asyncio
async def test_plugin_inventory_1to1_fiber_phases():
    """Verify pluginInventory.list returns 1:1 PluginInventorySnapshot with active fiber phases."""
    ctx = Context()
    loader = Loader(ctx)
    ctx.set_service("loader", loader)
    loader.register_plugin_class("@deepseek-ai/dsh-sample-plugin", SamplePlugin)
    loader.load_from_dict([
        {"id": "sample-plugin", "name": "@deepseek-ai/dsh-sample-plugin", "disabled": False}
    ])

    gateway = PluginInventoryGateway(ctx)
    snapshot = gateway.list()

    assert "entries" in snapshot
    assert len(snapshot["entries"]) == 1
    entry = snapshot["entries"][0]
    assert entry["entryId"] == "sample-plugin"
    assert entry["moduleName"] == "@deepseek-ai/dsh-sample-plugin"
    assert entry["enabled"] is True
    assert entry["fiberPhase"] == "active"


@pytest.mark.asyncio
async def test_agent_presets_1to1_schemas():
    """Verify agentPreset.* RPC methods conform 1:1 to TS agent-presets.ts contract."""
    ctx = Context()
    web_server = WebServerPlugin({"port": 0})
    api_proxy = ApiProxyPlugin()
    await ctx.registry.plugin(web_server, parent_ctx=ctx)
    await ctx.registry.plugin(api_proxy, parent_ctx=ctx)

    handler = api_proxy.agent_presets_handler

    # 1. list
    res_list = await handler.list_presets({})
    assert "presets" in res_list
    assert res_list["authorable"] is True
    assert res_list["hasDocument"] is True
    assert any(p["id"] == "standard" and p["isDefault"] is True and p["trust"] == "system" for p in res_list["presets"])

    # 2. select
    res_select = await handler.select_preset({"agentPreset": "minimal"})
    assert res_select == {"agentPreset": "minimal"}

    # 3. read
    res_read = await handler.read_preset({"agentPreset": "standard"})
    assert res_read["agentPreset"] == "standard"
    assert res_read["trust"] == "system"

    # 4. copy
    res_copy = await handler.copy_preset({"from": "standard", "agentPreset": "custom-std"})
    assert res_copy == {"agentPreset": "custom-std"}

    # 5. openDocument
    res_open = await handler.open_document({"agentPreset": "standard"})
    assert "opened" in res_open

    # 6. remove
    res_remove = await handler.remove_preset({"agentPreset": "custom-std"})
    assert res_remove == {}


@pytest.mark.asyncio
async def test_sessions_1to1_schemas_and_projections():
    """Verify session.* RPC methods conform 1:1 to TS sessions.ts contract."""
    ctx = Context()
    sessions_svc = SessionStore(ctx)
    ctx.set_service("sessions", sessions_svc)

    web_server = WebServerPlugin({"port": 0})
    api_proxy = ApiProxyPlugin()
    await ctx.registry.plugin(web_server, parent_ctx=ctx)
    await ctx.registry.plugin(api_proxy, parent_ctx=ctx)

    handler = api_proxy.sessions_handler

    # 1. create
    create_res = await handler.create_session({"sessionId": "session-test-1", "agentPreset": "creative"})
    assert create_res == {"sessionId": "session-test-1", "agentPreset": "creative"}

    # 2. list
    list_res = await handler.list_sessions({})
    assert "items" in list_res
    s_item = next(i for i in list_res["items"] if i["sessionId"] == "session-test-1")
    assert s_item["blank"] is True
    assert s_item["agentPreset"] == "creative"
    assert "projections" in s_item

    # 3. history
    hist_res = await handler.get_history({"sessionId": "session-test-1"})
    assert "events" in hist_res
    assert hist_res["hasMore"] is False
    assert "projections" in hist_res

    # 4. selectModel
    model_res = await handler.select_model({"sessionId": "session-test-1", "provider": "deepseek", "model": "deepseek-chat"})
    assert model_res == {"selected": {"provider": "deepseek", "model": "deepseek-chat"}}


@pytest.mark.asyncio
async def test_sse_event_target_resolution_non_default_session():
    """Verify SSE event handlers correctly resolve non-default sessionId from Session/Agent objects."""
    ctx = Context()
    web_server = WebServerPlugin({"port": 0})
    api_proxy = ApiProxyPlugin()
    await ctx.registry.plugin(web_server, parent_ctx=ctx)
    await ctx.registry.plugin(api_proxy, parent_ctx=ctx)

    sessions_svc = SessionStore(ctx)
    ctx.set_service("sessions", sessions_svc)
    session_custom = sessions_svc.create("session-custom-123")
    agent_custom = Agent(session=session_custom, ctx=ctx)

    broadcasted_mux = []
    broadcasted_host = []

    async def mock_mux(frame, rpc_id=None):
        broadcasted_mux.append(frame)

    async def mock_host(frame, rpc_id=None):
        broadcasted_host.append(frame)

    api_proxy._broadcast_mux = mock_mux
    api_proxy._broadcast_host = mock_host

    # Emit session event with custom Session object
    ev = session_custom.append("user/message", {"content": "Hello"})
    api_proxy._on_session_event(session_custom, ev)

    # Emit agent status
    api_proxy._on_agent_status({"agent": agent_custom, "status": "running"})

    await asyncio.sleep(0.01)

    assert len(broadcasted_mux) >= 1
    assert broadcasted_mux[-1]["sessionId"] == "session-custom-123"

    assert len(broadcasted_host) >= 1
    assert broadcasted_host[-1]["sessionId"] == "session-custom-123"
    assert broadcasted_host[-1]["running"] is True
