"""
Test 1:1 file structure and official Unary RPC methods for Web GUI ApiProxy.
"""

import pytest
import asyncio
from dsh.cordis.context import Context
from dsh.host.apiproxy.api_proxy import ApiProxyPlugin
from dsh.host.webserver.webserver import WebServerPlugin
from dsh.host.apiproxy.fetch.handler import OFFICIAL_RPC_METHODS
from dsh.host.apiproxy.api.rpc_map import OFFICIAL_RPC_METHODS as OFFICIAL_METHODS_CATALOG


def test_official_rpc_methods_catalog_size():
    """Verify that official RPC methods catalog is registered."""
    assert len(OFFICIAL_RPC_METHODS) == 55
    assert len(OFFICIAL_METHODS_CATALOG) == 55
    assert "session.attachment" in OFFICIAL_RPC_METHODS
    assert "session.updateQueue" in OFFICIAL_RPC_METHODS
    assert "agentPreset.select" in OFFICIAL_RPC_METHODS
    assert "settings.openDocument" in OFFICIAL_RPC_METHODS
    assert "pluginInventory.list" in OFFICIAL_RPC_METHODS


@pytest.mark.asyncio
async def test_apiproxy_all_domain_handlers():
    """Test dispatching of RPC methods across all domain handlers."""
    ctx = Context()
    web_server = WebServerPlugin({"port": 0})
    api_proxy = ApiProxyPlugin()

    ctx.plugin(web_server)
    ctx.plugin(api_proxy)

    assert api_proxy.agent_presets_handler is not None
    assert api_proxy.sessions_handler is not None
    assert api_proxy.settings_handler is not None
    assert api_proxy.host_handler is not None
    assert api_proxy.workspace_handler is not None

    # 1. session.attachment
    att_res = await api_proxy.sessions_handler.add_attachment({"sessionId": "s-1", "name": "doc.pdf"})
    assert att_res["attached"] is True
    assert att_res["name"] == "doc.pdf"

    # 2. session.updateQueue
    queue_res = await api_proxy.sessions_handler.update_queue({"sessionId": "s-1", "items": ["p1", "p2"]})
    assert queue_res["accepted"] is True

    # 3. agentPreset.select
    preset_res = await api_proxy.agent_presets_handler.select_preset({"agentPreset": "minimal"})
    assert preset_res["agentPreset"] == "minimal"

    # 4. settings.openDocument
    doc_res = await api_proxy.settings_handler.open_document({})
    assert doc_res["opened"] is True

    # 5. workspace.list
    ws_res = await api_proxy.workspace_handler.list_workspaces({})
    assert "items" in ws_res

    # 6. session.history format test
    hist_res = await api_proxy.sessions_handler.get_history({"sessionId": "s-1"})
    assert "events" in hist_res
    assert isinstance(hist_res["events"], list)
    if hist_res["events"]:
        assert "event" in hist_res["events"][0]
        assert "type" in hist_res["events"][0]["event"]

