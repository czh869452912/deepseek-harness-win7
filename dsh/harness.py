import os
from typing import Any, Dict, Optional
import yaml

from dsh.cordis.context import Context
from dsh.cordis.loader import PresetLoader
from dsh.plugins.agent_loop_plugin import AgentLoopPlugin
from dsh.plugins.cordis_manager import CordisManagerPlugin
from dsh.plugins.fs_local import FsLocalPlugin
from dsh.plugins.llm_openai import LLMOpenAIPlugin
from dsh.plugins.persona import PersonaPlugin
from dsh.plugins.tool_pwsh_persistent import ToolPwshPersistentPlugin
from dsh.plugins.tool_str_replace_editor import StrReplaceEditorPlugin


def build_harness(
    mode: str = "minimal",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    patch_file: Optional[str] = None
) -> Context:
    """
    Build and initialize a DeepSeek Harness Context with requested preset mode.
    """
    ctx = Context()

    # Mount base agent loop & LLM plugins
    ctx.plugin(AgentLoopPlugin)
    ctx.plugin(LLMOpenAIPlugin, config={
        "api_key": api_key,
        "base_url": base_url,
        "model": model
    })

    # Setup preset loader & register available plugins
    loader = PresetLoader()
    loader.register_plugin_class("@deepseek-ai/dsh-persona", PersonaPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-fs-local", FsLocalPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-str-replace-editor", StrReplaceEditorPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-tool-pwsh-persistent", ToolPwshPersistentPlugin)
    loader.register_plugin_class("@deepseek-ai/dsh-cordis-manager", CordisManagerPlugin)

    # Determine preset file
    presets_dir = os.path.join(os.path.dirname(__file__), "presets")
    if mode in ("minimal", "极简模式"):
        preset_path = os.path.join(presets_dir, "minimal.yaml")
    elif mode in ("creative", "cordis", "创造模式"):
        preset_path = os.path.join(presets_dir, "creative.yaml")
    else:
        # Assume custom filepath or default to minimal
        if os.path.exists(mode):
            preset_path = mode
        else:
            preset_path = os.path.join(presets_dir, "minimal.yaml")

    loader.load_preset_file(preset_path, ctx)

    # Apply patch overlay if specified
    if patch_file and os.path.exists(patch_file):
        print(f"[Cordis Harness] Applying patch overlay: {patch_file}")
        with open(patch_file, "r", encoding="utf-8") as f:
            patch_data = yaml.safe_load(f)
        if isinstance(patch_data, list):
            loader.load_from_dict(patch_data, ctx)

    return ctx
