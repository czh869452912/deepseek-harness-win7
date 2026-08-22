"""
Cordis Preset Loader service matching reference/vendor/loader/src/index.ts
Loads composition configs, supports cordis:group and isolated sub-realms.
"""

import os
import sys
import platform
from typing import Any, Dict, List, Optional, Union
import yaml

from dsh.cordis.context import Context
from dsh.cordis.service import Service
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


class Entry:
    """Represents a registered plugin entry in a Cordis composition tree matching vendor/loader/src/config/entry.ts."""
    def __init__(self, loader: Any, name: str, config: Optional[Dict[str, Any]] = None, disabled: bool = False, entry_id: Optional[str] = None, group: bool = False):
        self.loader = loader
        self.name = name
        self.config = config or {}
        self.disabled = disabled
        self.id = entry_id or name
        self.options = {
            "id": self.id,
            "name": self.name,
            "config": self.config,
            "group": group,
            "disabled": self.disabled,
        }
        self.fiber: Any = None

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"id": self.id, "name": self.name, "config": self.config}
        if self.disabled:
            res["disabled"] = self.disabled
        return res


# Backward compatibility alias
EntryNode = Entry


class Loader(Service):
    """
    Service that owns a loader entry tree and imports configured plugins.
    Registered on ctx.loader.
    """

    name = "loader"

    def __init__(self, ctx: Optional[Context] = None, config: Optional[Dict[str, Any]] = None):
        if ctx is not None:
            super().__init__(ctx, name="loader")
            self.ctx = ctx
        else:
            self.ctx = None
        self.config = config or {}
        self.registry_map: Dict[str, Any] = {}
        self.entries: List[Entry] = []

        if self.ctx:
            self.ctx.on("internal/config", self._on_internal_config)
            self.ctx.on("internal/update", self._on_internal_update)

    def _on_internal_config(self, fiber: Any, config: Any, next_fn: Any) -> Any:
        return next_fn(config)

    def _on_internal_update(self, fiber: Any, config: Any, no_save: bool, next_fn: Any) -> Any:
        return next_fn(config)

    def register_plugin_class(self, name_or_id: str, plugin_cls: Any) -> None:
        """
        Register a plugin class mapping (e.g., '@deepseek-ai/dsh-persona' -> PersonaPlugin).
        """
        self.registry_map[name_or_id] = plugin_cls

    def load_from_dict(self, config_items: List[Dict[str, Any]], target_ctx: Optional[Context] = None) -> None:
        """
        Load list of plugin configuration dicts onto context.
        """
        ctx = target_ctx or self.ctx
        if not ctx:
            raise RuntimeError("Cannot load plugins without a target Context")
        for item in config_items:
            plugin_name = item.get("name") or item.get("id")
            plugin_id = item.get("id", plugin_name)
            is_group = item.get("group", False) or plugin_name == "cordis:group"
            disabled_cond = item.get("disabled", False)

            is_disabled = eval_condition(disabled_cond)
            entry = Entry(loader=self, name=plugin_name, config=item.get("config"), disabled=is_disabled, entry_id=plugin_id, group=is_group)
            self.entries.append(entry)

            if is_disabled:
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

            if plugin_name in self.registry_map:
                plugin_cls = self.registry_map[plugin_name]
                fiber = None
                if isinstance(plugin_cls, type) and issubclass(plugin_cls, Plugin):
                    plugin_instance = plugin_cls(config=config)
                    plugin_instance.id = plugin_id
                    fiber = ctx.registry.plugin(plugin_instance, config=config)
                elif callable(plugin_cls):
                    fiber = ctx.registry.plugin(plugin_cls, config=config)
                else:
                    print(f"[Cordis Loader Warning] Registered item '{plugin_name}' is not a valid plugin", file=sys.stderr)
                entry.fiber = fiber
            else:
                print(f"[Cordis Loader Warning] Unknown plugin name/id: '{plugin_name}'", file=sys.stderr)

    def load_preset_file(self, filepath: str, target_ctx: Optional[Context] = None) -> None:
        """
        Load preset YAML file and mount onto context.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Preset file not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, list):
            self.load_from_dict(data, target_ctx)
        elif isinstance(data, dict) and "plugins" in data:
            self.load_from_dict(data["plugins"], target_ctx)
        else:
            raise ValueError(f"Invalid preset format in {filepath}")


# Backward compatibility alias
PresetLoader = Loader
