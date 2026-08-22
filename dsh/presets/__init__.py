"""
DeepSeek Harness Agent Presets module.
1:1 parity with reference @deepseek-ai/dsh-agent-presets package.
Python 3.8.10 compatible.
"""

from dsh.presets.agent_presets import SETTINGS_NAMESPACE, AgentPresets
from dsh.presets.authoring import (
    copy_composition,
    delete_composition,
    read_composition,
    writable_root,
)
from dsh.presets.discovery import (
    COMPOSITION_FILE,
    USER_PRESET_DIR,
    discover_presets,
    scan_root,
)
from dsh.presets.metadata import (
    METADATA_FILE,
    read_preset_metadata,
    render_preset_metadata,
)
from dsh.presets.preset import (
    PRESET_ID,
    AgentPreset,
    Config,
    InvalidPresetIdError,
    PresetExistsError,
    PresetMountError,
    PresetNotWritableError,
    PresetRoot,
    UnknownPresetError,
)
from dsh.presets.session import resolve_session_preset

__all__ = [
    "AgentPresets",
    "AgentPreset",
    "PresetRoot",
    "Config",
    "PRESET_ID",
    "UnknownPresetError",
    "PresetMountError",
    "InvalidPresetIdError",
    "PresetExistsError",
    "PresetNotWritableError",
    "COMPOSITION_FILE",
    "METADATA_FILE",
    "USER_PRESET_DIR",
    "SETTINGS_NAMESPACE",
    "discover_presets",
    "scan_root",
    "read_preset_metadata",
    "render_preset_metadata",
    "copy_composition",
    "delete_composition",
    "read_composition",
    "writable_root",
    "resolve_session_preset",
]
