from dsh.harness import build_harness


def test_build_harness_minimal_mode():
    ctx = build_harness(mode="minimal")

    plugins = [p["id"] for p in ctx.list_plugins()]
    assert "persona" in plugins
    assert "fs-local" in plugins
    assert "str-replace-editor" in plugins

    tools = [t.name for t in ctx.tools.list_tools()]
    assert "str_replace_editor" in tools
    assert "pwsh" in tools or "bash" in tools


def test_build_harness_creative_mode():
    ctx = build_harness(mode="creative")

    plugins = [p["id"] for p in ctx.list_plugins()]
    assert "cordis-manager" in plugins

    tools = [t.name for t in ctx.tools.list_tools()]
    assert "cordis_list_plugins" in tools
    assert "cordis_inspect_context" in tools
    assert "cordis_unload_plugin" in tools
    assert "cordis_dump_config" in tools
