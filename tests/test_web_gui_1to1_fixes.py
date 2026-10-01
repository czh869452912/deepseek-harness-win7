"""
Loader inventory phase regression. Historical ApiProxy cases are retired;
canonical transport and lifecycle replacements live in test_web_transport_retirement.py.
"""

import asyncio
import json
import pytest
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.plugin import Plugin
from dsh.host.plugin_inventory.plugin_inventory import PluginInventoryGateway, PluginInventoryPlugin


class SamplePlugin(Plugin):
    id = "sample-plugin"
    name = "@deepseek-ai/dsh-sample-plugin"


@pytest.mark.asyncio
async def test_plugin_inventory_1to1_fiber_phases():
    """Verify pluginInventory.list returns 1:1 PluginInventorySnapshot with active fiber phases."""
    ctx = Context()
    loader = Loader(ctx)
    loader.register_plugin_class("@deepseek-ai/dsh-sample-plugin", SamplePlugin)
    loader.load_from_dict([
        {"id": "sample-plugin", "name": "@deepseek-ai/dsh-sample-plugin", "disabled": False}
    ])
    # Mounting returns while the fiber is LOADING; the phase read below is a
    # settled-fiber contract.
    await asyncio.sleep(0)

    gateway = PluginInventoryGateway(ctx)
    snapshot = gateway.list()

    assert "entries" in snapshot
    assert len(snapshot["entries"]) == 1
    entry = snapshot["entries"][0]
    assert entry["entryId"] == "sample-plugin"
    assert entry["moduleName"] == "@deepseek-ai/dsh-sample-plugin"
    assert entry["enabled"] is True
    assert entry["fiberPhase"] == "active"
