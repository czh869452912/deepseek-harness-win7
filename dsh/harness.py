import asyncio
import os
from typing import Any, Dict, Optional
import yaml

from dsh.cordis.context import Context
from dsh.cordis.environment import load_layered_env
from dsh.cordis.loader import PresetLoader
from dsh.boot.plugin_registry import install_harness_plugin_classes
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.tools import ToolsPlugin
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.extensions.cli_visualizer import CliVisualizerPlugin
from dsh.llm.llm_openai import LLMOpenAIPlugin
from dsh.llm.token_meter import TokenMeterPlugin
from dsh.settings.settings_file import SettingsFilePlugin
from dsh.host.apiproxy.api_proxy import ApiProxyPlugin

from dsh.host.client_modules.registry import ClientModulesPlugin
from dsh.host.directory_picker.directory_picker import DirectoryPickerAutoPlugin
from dsh.host.frontend_static.frontend_static import FrontendStaticPlugin
from dsh.host.plugin_inventory.plugin_inventory import PluginInventoryPlugin
from dsh.host.webserver.webserver import WebServerPlugin
from dsh.interaction.commands import CommandsPlugin
from dsh.interaction.permission_presets import PermissionPresetsPlugin
from dsh.interaction.user_approval import UserApprovalPlugin
from dsh.llm.llm_retry import LLMRetryPlugin
from dsh.session.session_query import SessionQueryPlugin
from dsh.storage.storage import StoragePlugin
from dsh.workspace.workspace import WorkspacePlugin


def build_harness(
    mode: str = "standard",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    patch_file: Optional[str] = None,
    verbose: bool = True,
    enable_web: bool = False,
    web_host: str = "127.0.0.1",
    web_port: int = 8080,
) -> Context:
    """
    Build and initialize a DeepSeek Harness Context with requested preset mode.
    """
    ctx = Context()
    launch_env = load_layered_env("dsh", cwd=os.getcwd())
    from dsh.cordis.environment import DSH_LAUNCH_ENVIRONMENT_KEY, resolve_dsh_home
    ctx.provide(DSH_LAUNCH_ENVIRONMENT_KEY, launch_env)
    ctx.provide("launch_environment", launch_env)
    ctx.set_service("launch_environment", launch_env)

    # Provide cmdline args / appExit / appReady matching TS provideCmdline (D16)
    from dsh.boot.cmdline import provide_cmdline
    provide_cmdline(ctx, {
        "args": [],
        "exit": lambda code=0: None,
        "ready": None,
    })

    # Provide dshHomePath on ctx matching TS ctx.provide('dshHomePath', dshHomePath)
    def dsh_home_path(subpath: str = "") -> str:
        home = resolve_dsh_home()
        return os.path.join(home, subpath) if subpath else home
    ctx.provide("dshHomePath", dsh_home_path)
    ctx.dshHomePath = dsh_home_path
    ctx.dsh_home_path = dsh_home_path

    # Mount base infrastructure plugins
    ctx.plugin(ToolsPlugin)
    ctx.plugin(CredentialsLocalPlugin)
    ctx.plugin(SettingsFilePlugin)
    ctx.plugin(StoragePlugin)
    ctx.plugin(WorkspacePlugin)
    ctx.plugin(UserApprovalPlugin)
    ctx.plugin(PermissionPresetsPlugin)
    ctx.plugin(CommandsPlugin)
    ctx.plugin(TokenMeterPlugin)
    ctx.plugin(LLMRetryPlugin)
    if mode != "minimal":
        ctx.plugin(SessionQueryPlugin, config={"path": ":memory:", "open_at": "never"})
    ctx.plugin(AgentLoopPlugin)

    # Note: WebService is provided unconditionally on the root context so that plugins
    # with strict inject requirements (e.g. tool-web declaring inject=["web"]) can cleanly
    # resolve the service across both CLI and Web execution modes.
    from dsh.web.web_service import WebService
    ctx.set_service("web", WebService())

    if verbose:
        ctx.plugin(CliVisualizerPlugin, config={"verbose": True})

    ctx.plugin(LLMOpenAIPlugin, config={
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    })

    # Setup preset loader & register the installation-owned plugin set:
    # dsh.boot.plugin_registry owns the row-name -> plugin-class table.
    loader = PresetLoader(ctx)
    install_harness_plugin_classes(loader)

    if enable_web:
        ctx.plugin(WebServerPlugin, config={"host": web_host, "port": web_port})
        ctx.plugin(ClientModulesPlugin)
        ctx.plugin(PluginInventoryPlugin)
        ctx.plugin(DirectoryPickerAutoPlugin)
        ctx.plugin(ApiProxyPlugin)
        ctx.plugin(FrontendStaticPlugin)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    preset_file = os.path.join(base_dir, "presets", f"{mode}.yaml")
    if not os.path.isfile(preset_file):
        raise FileNotFoundError(f"dsh: failed to read preset at {preset_file}")

    # Load and apply patches (user home layer + CLI overlay layer + telemetry)
    from dsh.boot.app_boot import load_optional_patches, load_overlay_patches, assert_entries_loaded, assert_entries_activated_sync
    from dsh.cordis.profile import home_patch_path, resolve_telemetry_patch
    combined_patches = []
    user_patch_file = home_patch_path()
    if os.path.isfile(user_patch_file):
        opt = load_optional_patches("dsh", user_patch_file)
        if opt:
            combined_patches.extend(opt)

    if patch_file:
        if not os.path.exists(patch_file):
            raise FileNotFoundError(f"dsh: failed to read overlay {patch_file}: file not found")
        combined_patches.extend(load_overlay_patches("dsh", patch_file))

    # Incorporate DSH_TELEMETRY_DISABLED patch (D17)
    telemetry_patch = resolve_telemetry_patch(os.environ.get("DSH_TELEMETRY_DISABLED"), True)
    if telemetry_patch is not None:
        combined_patches.append(telemetry_patch)

    try:
        loader.load_preset_file(preset_file, ctx, patches=combined_patches if combined_patches else None)
        assert_entries_loaded(ctx, "dsh")
        assert_entries_activated_sync(ctx, "dsh")
    except Exception as exc:
        try:
            if hasattr(ctx, "teardown"):
                ctx.teardown()
            elif hasattr(ctx, "dispose"):
                ctx.dispose()
        except Exception:
            pass
        if isinstance(exc, (FileNotFoundError, ValueError)) and not str(exc).startswith("dsh:"):
            raise
        if str(exc).startswith("dsh:"):
            raise
        raise RuntimeError(f"dsh: plugin tree failed to load: {exc}") from exc

    return ctx
