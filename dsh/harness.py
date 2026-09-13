import asyncio
import inspect
import os
from typing import Any, Dict, Optional
import yaml

from dsh.cordis.context import Context
from dsh.cordis.environment import load_layered_env
from dsh.cordis.loader import PresetLoader
from dsh.context.agent_instructions import AgentInstructionsPlugin
from dsh.context.file_reference_local import FileReferenceLocalPlugin
from dsh.context.time_context import TimeContextPlugin
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.persona import PersonaPlugin
from dsh.core.tools import ToolsPlugin, ToolsService
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.extensions.cli_visualizer import CliVisualizerPlugin
from dsh.extensions.cordis_manager import CordisManagerPlugin
from dsh.fs.fs_local import FsLocalPlugin
from dsh.fs.tool_fs import ToolFsPlugin
from dsh.fs.tool_fs_search import ToolFsSearchPlugin
from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin
from dsh.interaction.tool_ask_user import ToolAskUserPlugin
from dsh.llm.llm_openai import LLMOpenAIPlugin
from dsh.llm.token_meter import TokenMeterPlugin
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
from dsh.compaction.pruner import ToolResultPrunerPlugin
from dsh.compaction.engine import BasicCompactionPlugin
from dsh.settings.settings_file import SettingsFilePlugin
from dsh.shell.tool_pwsh import ToolPwshPlugin
from dsh.shell.tool_pwsh_persistent import ToolPwshPersistentPlugin
from dsh.skill.skill_filesystem import SkillFilesystemPlugin
from dsh.skill.tool_skill import ToolSkillPlugin
from dsh.todo.tool_todo import ToolTodoPlugin
from dsh.plan.plan_mode import PlanModePlugin
from dsh.goal.tool_goal import ToolGoalPlugin
from dsh.guard.repeat_tool_reminder import RepeatToolReminderPlugin
from dsh.guard.timeout_policy import ToolCallTimeoutPolicyPlugin
from dsh.jobs.tool_jobs import ToolJobsPlugin
from dsh.spill.spill_store import SpillStorePlugin
from dsh.web.web_search_deepseek import WebSearchDeepSeekPlugin
from dsh.web.web_fetch_http import WebFetchHttpPlugin
from dsh.web.tool_web import ToolWebPlugin
from dsh.subagent.tool_subagent import ToolSubagentPlugin
from dsh.workflow.tool_ralph import ToolRalphPlugin
from dsh.workflow.tool_workflow import ToolWorkflowPlugin
from dsh.team.agent_team import AgentTeamPlugin
from dsh.team.tool_agent_team import ToolAgentTeamPlugin
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


async def build_harness(
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

    Mounting is asynchronous: `ctx.plugin()` returns once the fiber is LOADING,
    so every mount is awaited and the returned context has every mounted plugin
    active (or the startup audit raises). The reference boot path mounts the
    same way -- `await ctx.plugin(Loader)` and `await ctx.get('loader')?.await()`
    in packages/boot/app-boot/src/index.ts -- and this preset harness is the
    port's equivalent of that config-tree boot.
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
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(CredentialsLocalPlugin)
    await ctx.plugin(SettingsFilePlugin)
    await ctx.plugin(StoragePlugin)
    await ctx.plugin(WorkspacePlugin)
    await ctx.plugin(UserApprovalPlugin)
    await ctx.plugin(PermissionPresetsPlugin)
    await ctx.plugin(CommandsPlugin)
    await ctx.plugin(TokenMeterPlugin)
    await ctx.plugin(LLMRetryPlugin)
    if mode != "minimal":
        await ctx.plugin(SessionQueryPlugin, config={"path": ":memory:", "open_at": "never"})
    await ctx.plugin(AgentLoopPlugin)

    # Note: WebService is provided unconditionally on the root context so that plugins
    # with strict inject requirements (e.g. tool-web declaring inject=["web"]) can cleanly
    # resolve the service across both CLI and Web execution modes.
    from dsh.web.web_service import WebService
    ctx.set_service("web", WebService())

    if verbose:
        await ctx.plugin(CliVisualizerPlugin, config={"verbose": True})

    await ctx.plugin(LLMOpenAIPlugin, config={
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    })

    # Setup preset loader & register available plugins
    loader = PresetLoader(ctx)
    loader.register_plugin_class("@deepseek-ai/dsh-tools", ToolsPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-agent", AgentPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-persona", PersonaPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-agent-instructions", AgentInstructionsPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-file-reference-local", FileReferenceLocalPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-time-context", TimeContextPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-fs-local", FsLocalPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-fs", ToolFsPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-str-replace-editor", StrReplaceEditorPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-pwsh", ToolPwshPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-pwsh-persistent", ToolPwshPersistentPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-fs-search", ToolFsSearchPlugin)

    loader.register_plugin_class("@deepseek-ai/dsh-tool-ask-user", ToolAskUserPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-todo", ToolTodoPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-cordis-manager", CordisManagerPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-skill-filesystem", SkillFilesystemPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-skill", ToolSkillPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-credentials-local", CredentialsLocalPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-settings-file", SettingsFilePlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-storage", StoragePlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-workspace", WorkspacePlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-user-approval", UserApprovalPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-permission-presets", PermissionPresetsPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-commands", CommandsPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-llm-retry", LLMRetryPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-session-query-sqlite", SessionQueryPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-cli-visualizer", CliVisualizerPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-token-meter", TokenMeterPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-session-persistence-jsonl", JsonlSessionPersistencePlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-compaction-tool-result-pruner", ToolResultPrunerPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-compaction-basic", BasicCompactionPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-plan-mode", PlanModePlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-goal", ToolGoalPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-repeat-tool-reminder", RepeatToolReminderPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-call-timeout-policy", ToolCallTimeoutPolicyPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-jobs", ToolJobsPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-spill-local", SpillStorePlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-web-search-deepseek", WebSearchDeepSeekPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-web-fetch-http", WebFetchHttpPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-web", ToolWebPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-subagent", ToolSubagentPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-ralph", ToolRalphPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-workflow", ToolWorkflowPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-agent-team", AgentTeamPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-agent-team", ToolAgentTeamPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-host-webserver", WebServerPlugin)

    loader.register_plugin_class("@deepseek-ai/dsh-host-frontend-static", FrontendStaticPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-apiproxy", ApiProxyPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-client-modules", ClientModulesPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-host-directory-picker-auto", DirectoryPickerAutoPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-host-plugin-inventory", PluginInventoryPlugin)

    if enable_web:
        await ctx.plugin(WebServerPlugin, config={"host": web_host, "port": web_port})
        await ctx.plugin(ClientModulesPlugin)
        await ctx.plugin(PluginInventoryPlugin)
        await ctx.plugin(DirectoryPickerAutoPlugin)
        await ctx.plugin(ApiProxyPlugin)
        await ctx.plugin(FrontendStaticPlugin)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    preset_file = os.path.join(base_dir, "presets", f"{mode}.yaml")
    if not os.path.isfile(preset_file):
        raise FileNotFoundError(f"dsh: failed to read preset at {preset_file}")

    # Load and apply patches (user home layer + CLI overlay layer + telemetry)
    from dsh.boot.app_boot import (
        assert_entries_activated,
        assert_entries_loaded,
        load_optional_patches,
        load_overlay_patches,
        settle_fibers,
    )
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
        # `load_preset_file` mounts synchronously, so every entry it created is
        # still loading at this point; settle them before the activation audit.
        await settle_fibers(ctx)
        await assert_entries_activated(ctx, "dsh")
    except Exception as exc:
        # The reference boot catch awaits `ctx.fiber.dispose()` before it
        # relabels the failure (packages/boot/app-boot/src/index.ts:798-802),
        # so the partial tree's teardown has finished when the error escapes:
        # the spec asserts the partial setup was disposed and the tree owns no
        # pending task afterwards. A root fiber has no parent-owned
        # registration to drive its teardown, so a synchronous `ctx.teardown()`
        # only schedules the disposal and lets this raise with the cleanup still
        # pending; awaiting the settlement here owns it, and `settle_fibers`
        # then joins the dependent fiber inertia.
        try:
            root_fiber = getattr(ctx, "fiber", None)
            dispose = getattr(root_fiber, "dispose", None)
            if dispose is not None:
                settled = dispose()
                if inspect.isawaitable(settled):
                    await settled
            elif hasattr(ctx, "teardown"):
                ctx.teardown()
            elif hasattr(ctx, "dispose"):
                ctx.dispose()
            await settle_fibers(ctx)
        except Exception:
            pass
        if isinstance(exc, (FileNotFoundError, ValueError)) and not str(exc).startswith("dsh:"):
            raise
        if str(exc).startswith("dsh:"):
            raise
        raise RuntimeError(f"dsh: plugin tree failed to load: {exc}") from exc

    return ctx
