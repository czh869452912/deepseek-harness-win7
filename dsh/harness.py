import os
from typing import Any, Dict, Optional
import yaml

from dsh.cordis.context import Context
from dsh.cordis.environment import load_layered_env
from dsh.cordis.loader import PresetLoader
from dsh.context.agent_instructions import AgentInstructionsPlugin
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.persona import PersonaPlugin
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.extensions.cli_visualizer import CliVisualizerPlugin
from dsh.extensions.cordis_manager import CordisManagerPlugin
from dsh.fs.fs_local import FsLocalPlugin
from dsh.fs.tool_fs_search import ToolFsSearchPlugin
from dsh.fs.tool_str_replace_editor import StrReplaceEditorPlugin
from dsh.interaction.tool_ask_user import ToolAskUserPlugin
from dsh.llm.llm_openai import LLMOpenAIPlugin
from dsh.llm.token_meter import TokenMeterPlugin
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
from dsh.compaction.pruner import ToolResultPrunerPlugin
from dsh.compaction.engine import BasicCompactionPlugin
from dsh.settings.settings_file import SettingsFilePlugin
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
from dsh.host.webserver.webserver import WebServerPlugin
from dsh.host.frontend_static.frontend_static import FrontendStaticPlugin
from dsh.host.apiproxy.api_proxy import ApiProxyPlugin
from dsh.host.client_modules.registry import ClientModulesPlugin
from dsh.host.directory_picker.directory_picker import DirectoryPickerAutoPlugin


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
    launch_env = load_layered_env(cwd=os.getcwd())
    ctx.set_service("launch_environment", launch_env)

    # Mount base infrastructure plugins
    ctx.plugin(CredentialsLocalPlugin)
    ctx.plugin(SettingsFilePlugin)
    ctx.plugin(TokenMeterPlugin)
    ctx.plugin(AgentLoopPlugin)

    if verbose:
        ctx.plugin(CliVisualizerPlugin, config={"verbose": True})

    ctx.plugin(LLMOpenAIPlugin, config={
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    })

    # Setup preset loader & register available plugins
    loader = PresetLoader()
    loader.register_plugin_class("@deepseek-ai/dsh-agent", AgentPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-persona", PersonaPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-agent-instructions", AgentInstructionsPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-fs-local", FsLocalPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-str-replace-editor", StrReplaceEditorPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-pwsh-persistent", ToolPwshPersistentPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-fs-search", ToolFsSearchPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-ask-user", ToolAskUserPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-todo", ToolTodoPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-cordis-manager", CordisManagerPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-skill-filesystem", SkillFilesystemPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-skill", ToolSkillPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-credentials-local", CredentialsLocalPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-settings-file", SettingsFilePlugin)
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
    loader.register_plugin_class("@deepseek-ai/dsh-host-webserver", WebServerPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-host-frontend-static", FrontendStaticPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-apiproxy", ApiProxyPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-client-modules", ClientModulesPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-host-directory-picker-auto", DirectoryPickerAutoPlugin)

    if enable_web:
        ctx.plugin(WebServerPlugin, config={"host": web_host, "port": web_port})
        ctx.plugin(ClientModulesPlugin)
        ctx.plugin(DirectoryPickerAutoPlugin)
        ctx.plugin(ApiProxyPlugin)
        ctx.plugin(FrontendStaticPlugin)

    # Determine preset file
    presets_dir = os.path.join(os.path.dirname(__file__), "presets")
    if mode in ("minimal", "极简模式"):
        preset_path = os.path.join(presets_dir, "minimal.yaml")
    elif mode in ("standard", "标准模式"):
        preset_path = os.path.join(presets_dir, "standard.yaml")
    elif mode in ("creative", "cordis", "创造模式"):
        preset_path = os.path.join(presets_dir, "cordis.yaml")
    elif mode in ("code", "代码模式"):
        preset_path = os.path.join(presets_dir, "code.yaml")
    else:
        # Assume custom filepath or default to standard
        if os.path.exists(mode):
            preset_path = mode
        else:
            preset_path = os.path.join(presets_dir, "standard.yaml")

    loader.load_preset_file(preset_path, ctx)

    # Apply patch overlay if specified
    if patch_file and os.path.exists(patch_file):
        print(f"[Cordis Harness] Applying patch overlay: {patch_file}")
        with open(patch_file, "r", encoding="utf-8") as f:
            patch_data = yaml.safe_load(f)
        if isinstance(patch_data, list):
            loader.load_from_dict(patch_data, ctx)

    return ctx
