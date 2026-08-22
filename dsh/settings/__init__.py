"""
User-settings seam capability (`ctx.settings`).
Aligned 1:1 with reference @deepseek-ai/dsh-settings and @deepseek-ai/dsh-settings-file.
"""

from dsh.settings.provider import (
    SettingsConflictError,
    SettingsDescriptor,
    SettingsProvider,
    SettingsRegistration,
    SettingsScope,
    apply_path_op,
    clone_json_shaped,
    deep_equal_json,
    deep_freeze,
    install_settings_section,
    is_plain_object,
    merge_layers,
)
from dsh.settings.redact import (
    RedactedSecret,
    RedactedValue,
    redact_secrets,
)
from dsh.settings.settings_file import (
    FileSettingsProvider,
    ResolvedSpec,
    SettingsFilePlugin,
    SettingsService,
    patch_node,
    resolve_spec,
)
from dsh.settings.types import settings_namespace

__all__ = [
    "SettingsProvider",
    "FileSettingsProvider",
    "SettingsService",
    "SettingsScope",
    "SettingsRegistration",
    "SettingsDescriptor",
    "SettingsConflictError",
    "SettingsFilePlugin",
    "ResolvedSpec",
    "settings_namespace",
    "deep_equal_json",
    "is_plain_object",
    "apply_path_op",
    "clone_json_shaped",
    "merge_layers",
    "deep_freeze",
    "redact_secrets",
    "RedactedSecret",
    "RedactedValue",
    "install_settings_section",
    "resolve_spec",
    "patch_node",
]
