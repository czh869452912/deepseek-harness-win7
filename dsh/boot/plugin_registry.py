"""
Loader plugin-class resolution table for the dsh boot glue.

Every dsh surface launches a Cordis tree whose rows name npm packages
(`packages/bundle/*/cordis.patch.yml` in `dsh --profile <name>` profiles). The
Node runtime resolves those bare names through the installation's module graph:
the config project's own `node_modules` first, then the harness installation
closure the launcher heals into `$DSH_HOME/profiles/node_modules`
(`@deepseek-ai/dsh-app-boot`'s `healProfilesModuleFallback`).

The Python runtime has no Node module graph, so the installation-owned half of
that resolution is expressed here as a name -> plugin class table, and the boot
glue installs it on the Loader through `install_harness_plugin_classes` before
the config tree mounts. Resolution order is unchanged: a config-project-local
module always wins, and this table answers only when nothing else resolved.

Matching reference/packages/boot/app-boot/src/index.ts `boot`, which mounts the
Loader before the config tree so bare rows resolve from the installation.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import importlib
import os
from typing import Any, Dict, List, Optional

from dsh.boot.profile import PROFILE_MODULE_FALLBACK_DIR, PROFILES_DIR
from dsh.client.rows import CLIENT_HOST_HALF_ROWS
from dsh.cordis.environment import resolve_dsh_home

__all__ = [
    "HARNESS_PLUGIN_CLASSES",
    "harness_plugin_names",
    "harness_plugin_spec",
    "install_harness_plugin_classes",
    "installation_module_roots",
    "install_installation_module_roots",
    "resolve_harness_plugin",
]


def _load(package: str, spec: str) -> Any:
    """Import the 'module:Class' spec one installation-owned row names."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError(f"dsh: harness plugin entry {package} is not 'module:Class': {spec!r}")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attr)
    except AttributeError as error:
        raise AttributeError(
            f"dsh: harness plugin entry {package} names {spec}, but {module_name} declares no {attr}"
        ) from error


# The installation-owned plugin set, keyed by the npm row name a bundle patch
# uses. Each entry is that package's Python implementation: the port's plugin
# class where the upstream package mounts a row, or the class the upstream
# package default-exports. Vendored rows keep their vendored class.
HARNESS_PLUGIN_CLASSES: Dict[str, str] = {
    "@deepseek-ai/dsh-session-telemetry-otel": "dsh.session.telemetry:OpenTelemetrySessionBackend",
    "@deepseek-ai/dsh-cordis-host-runner": "dsh.extensions.host_runner:DynamicCordisRunner",
    "@deepseek-ai/dsh-session-log-export": "dsh.session.log_export:SessionLogExportPlugin",
    "@deepseek-ai/dsh-session-reference": "dsh.context.session_reference:SessionReferenceResolver",
    # Vendored Cordis plugins the bundles carry.
    "@deepseek-ai/cordis-plugin-hmr": "dsh.cordis.hmr:ConfigWatcherService",
    "@deepseek-ai/cordis-plugin-timer": "dsh.cordis.timer:TimerService",
    # Core spine.
    "@deepseek-ai/dsh-agent-spine-demo": "dsh.bundle.agent_spine:AgentSpine",
    "@deepseek-ai/dsh-system-prompt": "dsh.core.system_prompt.service:SystemPrompt",
    "@deepseek-ai/dsh-sdk-app": "dsh.bundle.sdk_app:SdkAppStartup",
    "@deepseek-ai/dsh-acp-app": "dsh.bundle.acp_app:AcpAppStartup",
    "@deepseek-ai/dsh-sdk-jsonrpc-server": "dsh.sdk.plugin:SdkJsonRpcPlugin",
    "@deepseek-ai/dsh-session": "dsh.core.session.session:SessionPlugin",
    "@deepseek-ai/dsh-agent": "dsh.core.agent:AgentPlugin",
    "@deepseek-ai/dsh-agent-loop": "dsh.core.agent_loop:AgentLoopPlugin",
    "@deepseek-ai/dsh-agent-default-model": "dsh.core.agent_default_model:AgentDefaultModelPlugin",
    "@deepseek-ai/dsh-agent-tool-presentation": "dsh.core.agent_tool_presentation:AgentToolPresentationPlugin",
    "@deepseek-ai/dsh-tools": "dsh.core.tools:ToolsPlugin",
    "@deepseek-ai/dsh-persona": "dsh.core.persona:PersonaPlugin",
    "@deepseek-ai/dsh-agent-instructions": "dsh.context.agent_instructions:AgentInstructionsPlugin",
    "@deepseek-ai/dsh-file-reference-local": "dsh.context.file_reference_local:FileReferenceLocalPlugin",
    "@deepseek-ai/dsh-time-context": "dsh.context.time_context:TimeContextPlugin",
    "@deepseek-ai/dsh-tmux-context": "dsh.context.tmux_context:TmuxContextPlugin",
    "@deepseek-ai/dsh-agent-presets/invariant": "dsh.presets.invariant:AgentPresetsInvariantPlugin",
    "@deepseek-ai/dsh-agent-presets": "dsh.presets.agent_presets:AgentPresets",
    # LLM capability and providers.
    "@deepseek-ai/dsh-llm": "dsh.llm.llm_service:LlmRuntime",
    "@deepseek-ai/dsh-llm-deepseek": "dsh.llm.llm_deepseek:LLMDeepSeekPlugin",
    "@deepseek-ai/dsh-llm-pi-ai": "dsh.llm.llm_pi_ai:LLMPiAiPlugin",
    "@deepseek-ai/dsh-plugin-package-inventory-deepseek": "dsh.llm.plugin_package_inventory:PluginPackageInventoryDeepSeek",
    "@deepseek-ai/dsh-deepseek-llm-api-extensions": "dsh.llm.deepseek_api_extensions:DeepSeekLlmApiExtensionRegistry",
    "@deepseek-ai/dsh-llm-openai": "dsh.llm.llm_openai:LLMOpenAIPlugin",
    "@deepseek-ai/dsh-llm-retry": "dsh.llm.llm_retry:LLMRetryPlugin",
    "@deepseek-ai/dsh-token-meter": "dsh.llm.token_meter:TokenMeterPlugin",
    # Session data, storage, settings, credentials.
    "@deepseek-ai/dsh-session-persistence-jsonl": "dsh.session.persistence_jsonl:JsonlSessionPersistencePlugin",
    "@deepseek-ai/dsh-session-persistence-sqlite": "dsh.session.persistence_sqlite:SqliteSessionPersistencePlugin",
    "@deepseek-ai/dsh-session-projection": "dsh.session.projections:SessionProjectionsPlugin",
    "@deepseek-ai/dsh-session-projection-cache": "dsh.session.projection_cache:SessionProjectionCachePlugin",
    "@deepseek-ai/dsh-session-query-sqlite": "dsh.session.session_query:SessionQueryPlugin",
    "@deepseek-ai/dsh-session-checkpoint-policy": "dsh.session.checkpoint_policy:SessionCheckpointPolicyPlugin",
    "@deepseek-ai/dsh-session-log-deepseek": "dsh.session.session_log_deepseek:SessionLogDeepSeekPlugin",
    "@deepseek-ai/dsh-session-stats": "dsh.session.stats:SessionStatsPlugin",
    "@deepseek-ai/dsh-session-title": "dsh.session.canonical_title:SessionTitleService",
    "@deepseek-ai/dsh-session-title-first-prompt-llm": "dsh.session.title_llm:FirstPromptTitlePlugin",
    "@deepseek-ai/dsh-typert-loader": "dsh.typert.loader:TypertLoader",
    "@deepseek-ai/dsh-api-gateway": "dsh.typert.gateway:TypertGatewayService",
    "@deepseek-ai/dsh-storage": "dsh.storage.hub:StoragePlugin",
    "@deepseek-ai/dsh-storage-json": "dsh.storage.plugins:StorageJsonPlugin",
    "@deepseek-ai/dsh-storage-domain": "dsh.storage.plugins:StorageDomainPlugin",
    "@deepseek-ai/dsh-settings-file": "dsh.settings.settings_file:SettingsFilePlugin",
    "@deepseek-ai/dsh-credentials-local": "dsh.credentials.credentials_local:CredentialsLocalPlugin",
    "@deepseek-ai/dsh-workspace": "dsh.workspace.workspace:WorkspacePlugin",
    # Filesystem, shell, subprocess, sandbox policy.
    "@deepseek-ai/dsh-sandbox-policy": "dsh.sandbox.sandbox_policy:SandboxPolicyService",
    "@deepseek-ai/dsh-sandbox-local": "dsh.sandbox.local:LocalSandboxProvider",
    "@deepseek-ai/dsh-pwsh-local": "dsh.shell.pwsh_executor:PwshLocalExecutor",
    # Win7 platform adaptation: the portable codeRuntime contract advertises
    # Python/process capabilities; it does not pretend to execute TypeScript.
    "@deepseek-ai/dsh-code-runtime-worker-thread": "dsh.code_runtime.process:PythonProcessRuntime",
    "@deepseek-ai/dsh-code-runtime-python-process": "dsh.code_runtime.process:PythonProcessRuntime",
    "@deepseek-ai/dsh-pwsh-sandbox": "dsh.shell.pwsh_executor:SandboxPwshExecutor",
    "@deepseek-ai/dsh-fs-local": "dsh.fs.fs_local:FsLocalPlugin",
    "@deepseek-ai/dsh-fs-sandbox": "dsh.fs.fs_sandbox:SandboxedFileSystem",
    "@deepseek-ai/dsh-fs-observation-policy": "dsh.fs.fs_observation_policy:FsObservationPolicyPlugin",
    "@deepseek-ai/dsh-tool-fs": "dsh.fs.tool_fs:ToolFsPlugin",
    "@deepseek-ai/dsh-tool-fs-search": "dsh.fs.tool_fs_search:ToolFsSearchPlugin",
    "@deepseek-ai/dsh-tool-str-replace-editor": "dsh.fs.tool_str_replace_editor:StrReplaceEditorPlugin",
    "@deepseek-ai/dsh-shell-env": "dsh.shell.shell_env:ShellEnvPlugin",
    "@deepseek-ai/dsh-tool-pwsh": "dsh.shell.canonical_tool_pwsh:CanonicalToolPwsh",
    "@deepseek-ai/dsh-tool-pwsh-persistent": "dsh.terminal.persistent_pwsh:PersistentPwshPlugin",
    "@deepseek-ai/dsh-terminal": "dsh.terminal.service:TerminalSessionService",
    "@deepseek-ai/dsh-terminal-bash": "dsh.terminal.local:LocalTerminalPlugin",
    "@deepseek-ai/dsh-subprocess-local": "dsh.subprocess.local:LocalSubprocessRuntime",
    # Interaction, jobs, delegation, skills, schedules.
    "@deepseek-ai/dsh-commands": "dsh.interaction.commands:CommandsPlugin",
    "@deepseek-ai/dsh-permission-presets": "dsh.interaction.permission_presets:PermissionPresetsPlugin",
    "@deepseek-ai/dsh-user-approval": "dsh.interaction.user_approval:UserApprovalPlugin",
    "@deepseek-ai/dsh-user-approval/invariant": "dsh.interaction.approval_invariant:ApprovalInvariantPlugin",
    "@deepseek-ai/dsh-user-questions": "dsh.interaction.user_questions:UserQuestionsPlugin",
    "@deepseek-ai/dsh-tool-ask-user": "dsh.interaction.tool_ask_user:ToolAskUserPlugin",
    "@deepseek-ai/dsh-jobs-local": "dsh.jobs.local:LocalJobRegistry",
    "@deepseek-ai/dsh-tool-jobs": "dsh.jobs.tool_jobs:ToolJobsPlugin",
    "@deepseek-ai/dsh-tool-todo": "dsh.todo.tool_todo:ToolTodoPlugin",
    "@deepseek-ai/dsh-tool-goal": "dsh.goal.tools:CanonicalToolGoal",
    "@deepseek-ai/dsh-command-goal": "dsh.goal.command:CommandGoal",
    "@deepseek-ai/dsh-goal": "dsh.goal.service:GoalService",
    "@deepseek-ai/dsh-goal-round-driver": "dsh.goal.driver:GoalRoundDriver",
    "@deepseek-ai/dsh-message-feedback": "dsh.feedback.message_feedback:MessageFeedbackPlugin",
    "@deepseek-ai/dsh-client-connection": "dsh.host.connection.canonical:CanonicalConnectionPlugin",
    "@deepseek-ai/dsh-client-hmr": "dsh.client.hmr:ClientHmrPlugin",
    "@deepseek-ai/dsh-command-feedback": "dsh.feedback.command_feedback:CommandFeedbackPlugin",
    "@deepseek-ai/dsh-agent-team": "dsh.team.agent_team:AgentTeamPlugin",
    "@deepseek-ai/dsh-tool-agent-team": "dsh.team.tool_agent_team:ToolAgentTeamPlugin",
    "@deepseek-ai/dsh-skill": "dsh.skill.registry:SkillRegistry",
    "@deepseek-ai/dsh-skill-filesystem": "dsh.skill.canonical_filesystem:CanonicalSkillFilesystem",
    "@deepseek-ai/dsh-tool-skill": "dsh.skill.canonical_tool:CanonicalToolSkill",
    "@deepseek-ai/dsh-tool-subagent": "dsh.subagent.canonical_tools:CanonicalToolSubagent",
    "@deepseek-ai/dsh-tool-subagent/model-selection-settings": "dsh.subagent.model_selection:ModelSelectionSettings",
    "@deepseek-ai/dsh-subagent": "dsh.subagent.runtime:SubagentPlugin",
    "@deepseek-ai/dsh-subagent-acp": "dsh.subagent.acp:SubagentAcp",
    "@deepseek-ai/dsh-subagent-spawn-in-process": "dsh.subagent.in_process:SpawnInProcess",
    "@deepseek-ai/dsh-subagent-fork-in-process": "dsh.subagent.in_process:ForkInProcess",
    "@deepseek-ai/dsh-tool-subagent-control": "dsh.subagent.control_tools:ToolSubagentControl",
    "@deepseek-ai/dsh-tool-subagent-control/list-agents": "dsh.subagent.control_tools:ToolListAgents",
    "@deepseek-ai/dsh-tool-subagent-report": "dsh.subagent.control_tools:ToolSubagentReport",
    "@deepseek-ai/dsh-tool-ralph": "dsh.workflow.tool_ralph:ToolRalphPlugin",
    "@deepseek-ai/dsh-tool-workflow": "dsh.workflow.tool_workflow:ToolWorkflowPlugin",
    "@deepseek-ai/dsh-workflow-worker-thread": "dsh.workflow.workflow_service:WorkflowEngine",
    "@deepseek-ai/dsh-schedule": "dsh.schedule:SchedulePlugin",
    "@deepseek-ai/dsh-mcp-client": "dsh.mcp.client:McpClientPlugin",
    # Compaction, spill, plan, guard.
    "@deepseek-ai/dsh-compaction-basic": "dsh.compaction.engine:CompactionBasicPlugin",
    "@deepseek-ai/dsh-compaction/invariant": "dsh.compaction.invariant:CompactionInvariantPlugin",
    "@deepseek-ai/dsh-compaction-basic/invariant": "dsh.compaction.invariant:CompactionBasicInvariantPlugin",
    "@deepseek-ai/dsh-command-compact/invariant": "dsh.compaction.invariant:CommandCompactInvariantPlugin",
    "@deepseek-ai/dsh-compaction-tool-result-pruner/invariant": "dsh.compaction.invariant:ToolResultPrunerInvariantPlugin",
    "@deepseek-ai/dsh-compaction-tool-result-pruner": "dsh.compaction.pruner:ToolResultPrunerPlugin",
    "@deepseek-ai/dsh-command-compact": "dsh.compaction.command_compact:CommandCompactPlugin",
    "@deepseek-ai/dsh-spill-local": "dsh.spill.spill_store:SpillStorePlugin",
    "@deepseek-ai/dsh-spill-policy": "dsh.spill.spill_policy:SpillPolicyPlugin",
    "@deepseek-ai/dsh-plan-mode": "dsh.plan.plan_mode:PlanModePlugin",
    "@deepseek-ai/dsh-repeat-tool-reminder": "dsh.guard.repeat_tool_reminder:RepeatToolReminderPlugin",
    "@deepseek-ai/dsh-tool-call-timeout-policy": "dsh.guard.timeout_policy:ToolCallTimeoutPolicyPlugin",
    # Web capability.
    "@deepseek-ai/dsh-web": "dsh.web.web_service:WebService",
    "@deepseek-ai/dsh-web-search-deepseek": "dsh.web.web_search_deepseek:WebSearchDeepSeekPlugin",
    "@deepseek-ai/dsh-web-fetch-http": "dsh.web.web_fetch_http:WebFetchHttpPlugin",
    "@deepseek-ai/dsh-tool-web": "dsh.web.tool_web:ToolWebPlugin",
    # Attachments, tracking, host surfaces, acp, extensions.
    "@deepseek-ai/dsh-attachment": "dsh.attachment.store:AttachmentStore",
    "@deepseek-ai/dsh-attachment-local": "dsh.attachment.local:LocalAttachmentStore",
    "@deepseek-ai/dsh-typert-registry": "dsh.typert.registry:TypertRegistry",
    "@deepseek-ai/dsh-api-remotes": "dsh.typert.api_remotes:ApiRemotesPlugin",
    "@deepseek-ai/dsh-api-session-controller": "dsh.api.session:SessionController",
    "@deepseek-ai/dsh-api-settings-controller": "dsh.api.settings:SettingsController",
    "@deepseek-ai/dsh-api-workspace-controller": "dsh.api.workspace:WorkspaceController",
    "@deepseek-ai/dsh-acp": "dsh.acp.server:AcpPlugin",
    "@deepseek-ai/dsh-client-modules": "dsh.host.client_modules.registry:ClientModulesPlugin",
    "@deepseek-ai/dsh-host-webserver": "dsh.host.webserver.webserver:WebServerPlugin",
    "@deepseek-ai/dsh-host-frontend-static": "dsh.host.frontend_static.frontend_static:FrontendStaticPlugin",
    "@deepseek-ai/dsh-host-plugin-inventory": "dsh.host.plugin_inventory.plugin_inventory:PluginInventoryPlugin",
    "@deepseek-ai/dsh-host-directory-picker-auto": "dsh.host.directory_picker.auto:DirectoryPickerAutoPlugin",
    "@deepseek-ai/dsh-host-directory-picker-browse": "dsh.host.directory_picker.browse:BrowseDirectoryPickerPlugin",
    "@deepseek-ai/dsh-host-directory-picker-native": "dsh.host.directory_picker.native:NativeDirectoryPickerPlugin",
    "@deepseek-ai/dsh-cli-visualizer": "dsh.extensions.cli_visualizer:CliVisualizerPlugin",
    # Bundle entry rows: each shipped app's command-line provider provides the
    # service that app's own runner row injects.
    "@deepseek-ai/dsh-web-app/startup": "dsh.bundle.web_app.startup:WebStartupPlugin",
    "@deepseek-ai/dsh-web-app": "dsh.bundle.web_app.runtime:WebRuntimePlugin",
    "@deepseek-ai/dsh-headless/startup": "dsh.bundle.headless.startup:HeadlessStartupPlugin",
    "@deepseek-ai/dsh-headless": "dsh.bundle.headless.runner:HeadlessRunnerPlugin",
    # The self-inspection toolset publishes itself as `dsh-tool-cordis`; profiles
    # composed before that rename name the `dsh-cordis-manager` row.
    "@deepseek-ai/dsh-tool-cordis": "dsh.extensions.cordis_manager:CordisManagerPlugin",
    "@deepseek-ai/dsh-cordis-manager": "dsh.extensions.cordis_manager:CordisManagerPlugin",
}

# The browser client rows the Web bundle mounts: each package's host half, so
# the modules node half discovers its `dsh.client` declaration. Kept in one
# table (dsh/client/rows.py) so a row and its implementation cannot drift.
HARNESS_PLUGIN_CLASSES.update(CLIENT_HOST_HALF_ROWS)


def harness_plugin_names() -> List[str]:
    """Return every npm row name the installation-owned table answers for."""
    return sorted(HARNESS_PLUGIN_CLASSES)


def harness_plugin_spec(name: str) -> Optional[str]:
    """Return the 'module:Class' spec one installation-owned row names, if any."""
    return HARNESS_PLUGIN_CLASSES.get(name)


def resolve_harness_plugin(name: str) -> Optional[Any]:
    """
    Resolve one bare row name against the installation-owned table.

    @param name: the bare package name a loader entry or preset row names.
    @returns: the plugin or service class, or None when the installation does
        not carry that package.
    """
    spec = HARNESS_PLUGIN_CLASSES.get(name)
    if spec is None:
        return None
    return _load(name, spec)


def installation_module_roots(config_path: str, dsh_home: Optional[str] = None) -> List[str]:
    """
    Return the healed installation fallback node_modules levels a booted tree
    resolves installation packages from.

    Matching `healProfilesModuleFallback`
    (reference/packages/boot/app-boot/src/profile.ts): the shared
    `$DSH_HOME/profiles/node_modules` closure plus the profile-owned projection
    `<profile>/.dsh-module-fallback/node_modules`.

    @param config_path: the absolute root config path the tree mounts.
    @param dsh_home: the Harness home; defaults to `resolve_dsh_home()`.
    @returns: the fallback node_modules directories, in resolution order.
    """
    home = dsh_home or resolve_dsh_home()
    profile_dir = os.path.dirname(os.path.abspath(config_path))
    return [
        os.path.join(home, PROFILES_DIR, "node_modules"),
        os.path.join(profile_dir, PROFILE_MODULE_FALLBACK_DIR, "node_modules"),
    ]


def install_installation_module_roots(
    loader: Any, config_path: str, dsh_home: Optional[str] = None
) -> List[str]:
    """
    Install the healed installation fallback roots on a Loader.

    The Loader is read through a service proxy, so the roots are written into the
    list the service owns rather than rebound on the proxy.

    @param loader: the Loader whose entries resolve bare row names.
    @param config_path: the absolute root config path the tree mounts.
    @param dsh_home: the Harness home; defaults to `resolve_dsh_home()`.
    @returns: the installed fallback node_modules directories.
    """
    roots = installation_module_roots(config_path, dsh_home)
    installed = getattr(loader, "installation_module_roots", None)
    if isinstance(installed, list):
        installed[:] = roots
        return installed
    loader.installation_module_roots = roots
    return roots


def install_harness_plugin_classes(loader: Any) -> Dict[str, Any]:
    """
    Install the installation-owned resolution table on a Loader.

    The table is a fallback, not a primary registry: the Loader consults it only
    after the config project's own module resolution fails, matching the Node
    runtime, where the healed installation closure is the last anchor.

    The Loader is read through a service proxy, so the table is installed into
    the mapping the service owns rather than rebound on the proxy.

    @param loader: the Loader whose entries resolve bare row names.
    @returns: the installed name -> class mapping.
    """
    table: Dict[str, Any] = {}
    for name, spec in HARNESS_PLUGIN_CLASSES.items():
        table[name] = _load(name, spec)
    installed = getattr(loader, "harness_plugins", None)
    if isinstance(installed, dict):
        installed.clear()
        installed.update(table)
        return installed
    loader.harness_plugins = table
    return table


# CamelCase aliases for TS parity
harnessPluginNames = harness_plugin_names
harnessPluginSpec = harness_plugin_spec
resolveHarnessPlugin = resolve_harness_plugin
installHarnessPluginClasses = install_harness_plugin_classes
installationModuleRoots = installation_module_roots
