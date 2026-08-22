import os
import sys
import platform
from typing import Any, Dict, List, Optional
import yaml

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin


def js_constructor(loader: Any, node: Any) -> str:
    return f"!!js {loader.construct_scalar(node)}"

try:
    yaml.SafeLoader.add_constructor('tag:yaml.org,2002:js', js_constructor)
    yaml.SafeLoader.add_constructor('!!js', js_constructor)
except Exception:
    pass


def eval_condition(condition: Any) -> bool:
    """
    Safely evaluate boolean expression for 'disabled' or 'enabled' fields in plugin configs.
    Example: sys.platform == 'win32' or platform.system() == 'Windows'
    """
    if not condition:
        return False
    if isinstance(condition, bool):
        return condition

    cond_str = str(condition).strip()
    if cond_str.startswith("!!js"):
        cond_str = cond_str[4:].strip()

    cond_str = cond_str.replace("process.platform === 'win32'", "sys.platform == 'win32'")
    cond_str = cond_str.replace("process.platform !== 'win32'", "sys.platform != 'win32'")
    cond_str = cond_str.replace("process.platform === 'posix'", "sys.platform != 'win32'")

    scope = {
        "sys": sys,
        "os": os,
        "platform": platform,
        "env": os.environ
    }
    try:
        return bool(eval(cond_str, {"__builtins__": {}}, scope))
    except Exception as e:
        print(f"[Cordis Loader Warning] Failed to evaluate condition '{condition}': {e}", file=sys.stderr)
        return False


class PresetLoader:
    """
    Loads Cordis preset configuration YAML files and mounts plugins onto Context.
    Supports cordis:group and isolated sub-realms matching 1:1 official specifications.
    """

    def __init__(self, plugin_registry: Optional[Dict[str, Any]] = None):
        self.registry: Dict[str, Any] = plugin_registry or {}

    def register_plugin_class(self, name_or_id: str, plugin_cls: Any) -> None:
        """
        Register a plugin class mapping (e.g., '@deepseek-ai/dsh-persona' -> PersonaPlugin).
        """
        self.registry[name_or_id] = plugin_cls

    def load_from_dict(self, config_items: List[Dict[str, Any]], ctx: Context) -> None:
        """
        Load list of plugin configuration dicts onto context.
        """
        for item in config_items:
            plugin_name = item.get("name") or item.get("id")
            plugin_id = item.get("id", plugin_name)
            is_group = item.get("group", False) or plugin_name == "cordis:group"
            disabled_cond = item.get("disabled", False)

            if eval_condition(disabled_cond):
                continue

            if is_group:
                nested_items = item.get("config", [])
                isolate_config = item.get("isolate", None)

                if isolate_config:
                    sub_ctx = ctx.isolate(isolate_config)
                    self.load_from_dict(nested_items, sub_ctx)
                else:
                    self.load_from_dict(nested_items, ctx)
                continue

            config = item.get("config", {})

            if plugin_name in self.registry:
                plugin_cls = self.registry[plugin_name]
                if isinstance(plugin_cls, type) and issubclass(plugin_cls, Plugin):
                    plugin_instance = plugin_cls(config=config)
                    plugin_instance.id = plugin_id
                    ctx.plugin(plugin_instance)
                elif callable(plugin_cls):
                    plugin_cls(ctx, config)
                else:
                    print(f"[Cordis Loader Warning] Registered item '{plugin_name}' is not a valid plugin", file=sys.stderr)
            else:
                print(f"[Cordis Loader Warning] Unknown plugin name/id: '{plugin_name}'", file=sys.stderr)

    def load_preset_file(self, filepath: str, ctx: Context) -> None:
        """
        Load preset YAML file and mount onto context.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Preset file not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, list):
            self.load_from_dict(data, ctx)
        elif isinstance(data, dict) and "plugins" in data:
            self.load_from_dict(data["plugins"], ctx)
        else:
            raise ValueError(f"Invalid preset format in {filepath}")
