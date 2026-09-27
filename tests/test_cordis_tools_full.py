import json
import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.extensions.cordis_manager import CordisManagerPlugin, DynamicCordisRunnerService


@pytest.fixture
def cordis_ctx():
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service("tools", tools)
    ctx.plugin(CordisManagerPlugin)
    return ctx


@pytest.mark.asyncio
async def test_cordis_inspect_list(cordis_ctx):
    tools: ToolsService = cordis_ctx.get("tools")
    res_str = await tools.execute_tool("cordis_inspect_list", {})
    data = json.loads(res_str)
    assert "providers" in data
    provider_ids = [p["id"] for p in data["providers"]]
    assert "Service" in provider_ids
    assert "Event" in provider_ids
    assert "Builtin" in provider_ids
    assert "Tool" in provider_ids


@pytest.mark.asyncio
async def test_cordis_inspect_query(cordis_ctx):
    tools: ToolsService = cordis_ctx.get("tools")

    # Query Service
    res_str = await tools.execute_tool("cordis_inspect_query", {
        "platform": "host",
        "provider": "Service",
        "method": "listService",
        "input": {"service": "tools"}
    })
    data = json.loads(res_str)
    assert data.get("service") == "tools"
    assert "methods" in data

    # Query Builtin
    res_builtin = await tools.execute_tool("cordis_inspect_query", {
        "platform": "host",
        "provider": "Builtin",
        "method": "listBuiltins",
    })
    builtin_data = json.loads(res_builtin)
    assert "builtins" in builtin_data


@pytest.mark.asyncio
async def test_cordis_lifecycle_define_run_stop_undefine(cordis_ctx):
    tools: ToolsService = cordis_ctx.get("tools")

    # 1. Define new plugin
    define_res_str = await tools.execute_tool("cordis_define", {
        "plugin": {"kind": "new", "idPrefix": "theme"},
        "name": "Custom Dark Theme",
        "purpose": "Provide user dark theme palette",
        "code": {
            "host": "module.exports = function(ctx) { ctx.provide('theme', { mode: 'dark' }); }",
            "client": "export default function(ctx) { console.log('theme loaded'); }"
        }
    })
    define_data = json.loads(define_res_str)
    assert "pluginId" in define_data
    assert "packageId" in define_data
    assert define_data["hasHostHalf"] is True
    assert define_data["hasClientHalf"] is True

    plugin_id = define_data["pluginId"]
    package_id = define_data["packageId"]

    # 2. Inspect self (list mode)
    self_list_str = await tools.execute_tool("cordis_inspect_self", {})
    self_list = json.loads(self_list_str)
    assert self_list["mode"] == "plugins"
    assert any(p["pluginId"] == plugin_id for p in self_list["plugins"])

    # 3. Inspect self (plugin mode)
    self_plugin_str = await tools.execute_tool("cordis_inspect_self", {"pluginId": plugin_id})
    self_plugin = json.loads(self_plugin_str)
    assert self_plugin["mode"] == "plugin"
    assert len(self_plugin["packages"]) == 1

    # 4. Inspect self (package mode)
    self_pkg_str = await tools.execute_tool("cordis_inspect_self", {"pluginId": plugin_id, "packageId": package_id})
    self_pkg = json.loads(self_pkg_str)
    assert self_pkg["mode"] == "package"
    assert self_pkg["code"]["host"] is not None

    # 5. Run package
    run_res_str = await tools.execute_tool("cordis_run", {
        "pluginId": plugin_id,
        "packageId": package_id,
        "mode": "run"
    })
    run_data = json.loads(run_res_str)
    assert run_data["status"] == "running"
    assert run_data["currentPackageId"] == package_id

    # 6. Stop plugin
    stop_res_str = await tools.execute_tool("cordis_stop", {"pluginId": plugin_id})
    stop_data = json.loads(stop_res_str)
    assert stop_data["ok"] is True

    # 7. Undefine plugin
    undef_res_str = await tools.execute_tool("cordis_undefine", {"pluginId": plugin_id})
    undef_data = json.loads(undef_res_str)
    assert undef_data["ok"] is True
    assert undef_data["pluginId"] == plugin_id


@pytest.mark.asyncio
async def test_cordis_backward_compatibility_aliases(cordis_ctx):
    tools: ToolsService = cordis_ctx.get("tools")

    list_res = await tools.execute_tool("cordis_list_plugins", {})
    assert isinstance(list_res, str)

    inspect_res = await tools.execute_tool("cordis_inspect_context", {})
    inspect_data = json.loads(inspect_res)
    assert "services" in inspect_data


def test_cordis_define_schema_keeps_required_at_object_level(cordis_ctx):
    """The TS oneOf branches use an object-level required list."""
    tool = cordis_ctx.get("tools").get_tool("cordis_define")
    branches = tool.parameters["properties"]["plugin"]["oneOf"]
    assert [branch["required"] for branch in branches] == [["kind", "idPrefix"], ["kind", "pluginId"]]
    for branch in branches:
        assert "required" not in branch["properties"]["kind"]
