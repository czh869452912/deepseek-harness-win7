"""
Host halves of the browser client plugins (`@deepseek-ai/dsh-client-*`).

Port of the node half of the packages under `reference/packages/client/*` plus
`reference/packages/extensions/ui-cordis`. A `dsh.client` row mounts in the host
tree so its package is a Loader entry: the modules node half
(`dsh/host/client_modules/registry.py`) discovers the package's `dsh.client`
declaration there and serves its `./client` bundle to the browser.

Every class below is the exact upstream host half: an empty `apply` whose only
effect is that the row appears in the host composition. The settings-backed
rows and the file-reference row carry real host behavior and live in
`dsh/client/settings_sections.py` and `dsh/client/deliverables.py`.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, Tuple

from dsh.cordis.plugin import Plugin

__all__ = ["EMPTY_HOST_HALVES", "bind_empty_host_halves"]


def _empty_host_half(class_name: str, package_name: str, upstream: str) -> type:
    """
    Build one browser row's host half.

    @param class_name: the module attribute name the row table names.
    @param package_name: the `dsh.client` package name the row mounts.
    @param upstream: the reference source this empty half is the port of.
    @returns: a mountable plugin class whose `apply` contributes nothing.
    """

    def apply(self: Any, ctx: Any) -> None:
        """Host plugin body: no host-side behavior for this surface plugin."""
        return None

    return type(
        class_name,
        (Plugin,),
        {
            "id": package_name,
            "name": package_name,
            "apply": apply,
            "__doc__": "Host half of %s (port of %s): no host-side behavior." % (package_name, upstream),
        },
    )


# Class name -> (package name, reference source). Each class is bound below
# under its own name, so the row table can name it as a module attribute.
EMPTY_HOST_HALVES: Dict[str, Tuple[str, str]] = {
    "ClientUiDirectoryPickerNativePlugin": (
        "@deepseek-ai/dsh-client-ui-directory-picker-native", "packages/client/ui-directory-picker-native/src/index.ts",
    ),
    "ClientUiDirectoryPickerBrowsePlugin": (
        "@deepseek-ai/dsh-client-ui-directory-picker-browse", "packages/client/ui-directory-picker-browse/src/index.ts",
    ),
    "CordisClientRunnerPlugin": (
        "@deepseek-ai/dsh-cordis-client-runner",
        "packages/extensions/cordis-client-runner/src/index.ts",
    ),
    "ClientUiAgentPresetPlugin": (
        "@deepseek-ai/dsh-client-ui-agent-preset",
        "packages/client/ui-agent-preset/src/index.ts",
    ),
    "ClientUiApprovalPlugin": ("@deepseek-ai/dsh-client-ui-approval", "packages/client/ui-approval/src/index.ts"),
    "ClientUiAttachmentPlugin": (
        "@deepseek-ai/dsh-client-ui-attachment",
        "packages/client/ui-attachment/src/index.ts",
    ),
    "ClientUiBrandOfficialPlugin": (
        "@deepseek-ai/dsh-client-ui-brand-official",
        "packages/client/ui-brand-official/src/index.ts",
    ),
    "ClientUiCommandsPlugin": ("@deepseek-ai/dsh-client-ui-commands", "packages/client/ui-commands/src/index.ts"),
    "ClientUiCordisPlugin": ("@deepseek-ai/dsh-client-ui-cordis", "packages/extensions/ui-cordis/src/index.ts"),
    "ClientUiGoalPlugin": ("@deepseek-ai/dsh-client-ui-goal", "packages/client/ui-goal/src/index.ts"),
    "ClientUiInputTriggerPlugin": (
        "@deepseek-ai/dsh-client-ui-input-trigger",
        "packages/client/ui-input-trigger/src/index.ts",
    ),
    "ClientUiJobsPlugin": ("@deepseek-ai/dsh-client-ui-jobs", "packages/client/ui-jobs/src/index.ts"),
    "ClientUiLayoutPlugin": ("@deepseek-ai/dsh-client-ui-layout", "packages/client/ui-layout/src/index.ts"),
    "ClientUiMessageFeedbackPlugin": (
        "@deepseek-ai/dsh-client-ui-message-feedback",
        "packages/client/ui-message-feedback/src/index.ts",
    ),
    "ClientUiModelSelectionPlugin": (
        "@deepseek-ai/dsh-client-ui-model-selection",
        "packages/client/ui-model-selection/src/index.ts",
    ),
    "ClientUiPermissionPresetsPlugin": (
        "@deepseek-ai/dsh-client-ui-permission-presets",
        "packages/client/ui-permission-presets/src/index.ts",
    ),
    "ClientUiPlanPlugin": ("@deepseek-ai/dsh-client-ui-plan", "packages/client/ui-plan/src/index.ts"),
    "ClientUiReferencePlugin": (
        "@deepseek-ai/dsh-client-ui-reference",
        "packages/client/ui-reference/src/index.ts",
    ),
    "ClientUiRendererPlugin": ("@deepseek-ai/dsh-client-ui-renderer", "packages/client/ui-renderer/src/index.ts"),
    "ClientUiSessionPlugin": ("@deepseek-ai/dsh-client-ui-session", "packages/client/ui-session/src/index.ts"),
    "ClientUiSettingsPlugin": ("@deepseek-ai/dsh-client-ui-settings", "packages/client/ui-settings/src/index.ts"),
    "ClientUiSettingsModelsPlugin": (
        "@deepseek-ai/dsh-client-ui-settings-models",
        "packages/client/ui-settings-models/src/index.ts",
    ),
    "ClientUiSettingsPluginInventoryPlugin": (
        "@deepseek-ai/dsh-client-ui-settings-plugin-inventory",
        "packages/client/ui-settings-plugin-inventory/src/index.ts",
    ),
    "ClientUiSettingsPluginsPlugin": (
        "@deepseek-ai/dsh-client-ui-settings-plugins",
        "packages/client/ui-settings-plugins/src/index.ts",
    ),
    "ClientUiSidebarPlugin": ("@deepseek-ai/dsh-client-ui-sidebar", "packages/client/ui-sidebar/src/index.ts"),
    "ClientUiSkillPlugin": ("@deepseek-ai/dsh-client-ui-skill", "packages/client/ui-skill/src/index.ts"),
    "ClientUiSubagentPlugin": ("@deepseek-ai/dsh-client-ui-subagent", "packages/client/ui-subagent/src/index.ts"),
    "ClientUiToolPlugin": ("@deepseek-ai/dsh-client-ui-tool", "packages/client/ui-tool/src/index.ts"),
    "ClientUiTrajectoryPlugin": (
        "@deepseek-ai/dsh-client-ui-trajectory",
        "packages/client/ui-trajectory/src/index.ts",
    ),
    "ClientUiUserQuestionsPlugin": (
        "@deepseek-ai/dsh-client-ui-user-questions",
        "packages/client/ui-user-questions/src/index.ts",
    ),
    "ClientUiWorkflowRunPlugin": (
        "@deepseek-ai/dsh-client-ui-workflow-run",
        "packages/client/ui-workflow-run/src/index.ts",
    ),
    "ClientUiWorkspacePlugin": ("@deepseek-ai/dsh-client-ui-workspace", "packages/client/ui-workspace/src/index.ts"),
}


def bind_empty_host_halves() -> None:
    """Bind each generated class to its module attribute for the row table."""
    for class_name, (package_name, upstream) in EMPTY_HOST_HALVES.items():
        globals()[class_name] = _empty_host_half(class_name, package_name, upstream)


bind_empty_host_halves()
