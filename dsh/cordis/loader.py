"""
Cordis Composition & Loader System matching reference/vendor/loader/src/*
Implements EntryTree, EntryGroup, Entry, and Loader service.
"""

import asyncio
import os
import platform
import random
import sys
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union
import yaml

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


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
        sys.stderr.write(f"[Cordis Loader Warning] Failed to evaluate condition '{condition}': {e}\n")
        return False


import copy

def apply_entry_patches(
    data: List[Dict[str, Any]],
    patches: Optional[List[Dict[str, Any]]],
    warn: Optional[Callable[..., None]] = None,
) -> List[Dict[str, Any]]:
    """
    Apply patch lists to an entry list matching reference/vendor/include/src/index.ts#applyEntryPatches.
    Never mutates input, returns detached deep copy.
    """
    result = copy.deepcopy(data)
    if not patches:
        return result

    def _warn(msg: str, *args: Any) -> None:
        if warn:
            warn(msg, *args)
        else:
            sys.stderr.write(f"[Cordis Loader Patch Warning] {msg % args if args else msg}\n")

    entry_map: Dict[str, Dict[str, Any]] = {}

    def build_map(entries: List[Dict[str, Any]]) -> None:
        for entry in entries:
            eid = entry.get("id")
            if eid:
                entry_map[eid] = entry
            if entry.get("group") and isinstance(entry.get("config"), list):
                build_map(entry["config"])

    build_map(result)

    for patch in patches:
        patch_copy = dict(patch)
        pid = patch_copy.get("id")
        insert = patch_copy.pop("insert", None)
        pname = patch_copy.pop("name", None)

        if insert is not None:
            cloned_insert = copy.deepcopy(insert)
            if pid:
                target = entry_map.get(pid)
                if not target:
                    _warn("patch insert: entry '%s' not found", pid)
                    continue
                if not target.get("group"):
                    _warn("patch insert: entry '%s' is not a group", pid)
                    continue
                if not isinstance(target.get("config"), list):
                    target["config"] = []
                target["config"].extend(cloned_insert)
            else:
                result.extend(cloned_insert)
            build_map(cloned_insert)
            continue

        if not pid:
            _warn("patch: id is required for non-insert patches")
            continue

        target = entry_map.get(pid)
        if not target:
            _warn("patch: entry '%s' not found", pid)
            continue

        if pname and pname != target.get("name"):
            _warn("patch: name mismatch for '%s' (expected '%s', got '%s'), skipping", pid, target.get("name"), pname)
            continue

        for key, value in patch_copy.items():
            if key == "id":
                continue
            target[key] = value

    return result


class EntryTree:
    """
    Mutable tree of loader entries matching reference/vendor/loader/src/config/tree.ts.
    Persistence is supplied by subclasses or write() implementations.
    """
    sep = ":"

    def __init__(self, ctx: Context):
        self.ctx = ctx.extend()
        self.enable_logs = True
        self.store: Dict[str, "Entry"] = {}
        self.root = EntryGroup(self.ctx, self)
        fiber_entry = getattr(getattr(self.ctx, "fiber", None), "entry", None)
        if fiber_entry:
            fiber_entry.subtree = self

    def entries(self) -> Iterator["Entry"]:
        """Iterate entries in this tree and any nested subtrees."""
        for entry in list(self.store.values()):
            yield entry
            if entry.subtree:
                yield from entry.subtree.entries()

    def get_tasks(self) -> List[Any]:
        """Return pending import and lifecycle tasks owned by this tree."""
        tasks = []
        for entry in self.entries():
            if entry._init_task:
                tasks.append(entry._init_task)
            elif entry.fiber and entry.fiber.inertia:
                tasks.append(entry.fiber.inertia)
        return tasks

    async def await_tasks(self) -> None:
        """Wait until this tree has no active import or lifecycle tasks."""
        while True:
            tasks = self.get_tasks()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                continue
            break

    def ensure_id(self, options: Dict[str, Any]) -> str:
        if not options.get("id"):
            while True:
                eid = hex(random.randint(0x10000000, 0xFFFFFFFF))[2:]
                if eid not in self.store:
                    options["id"] = eid
                    break
        return str(options["id"])

    def resolve(self, entry_id: str) -> "Entry":
        """Resolve an entry by id, including nested ids separated by EntryTree.sep."""
        parts = entry_id.split(self.sep)
        tree: Optional["EntryTree"] = self
        final = parts.pop()
        for part in parts:
            if tree and part in tree.store:
                tree = tree.store[part].subtree
            else:
                tree = None
            if not tree:
                raise KeyError(f"Cannot resolve entry {entry_id}")
        if not tree or final not in tree.store:
            raise KeyError(f"Cannot resolve entry {entry_id}")
        return tree.store[final]

    def resolve_group(self, group_id: Optional[str]) -> "EntryGroup":
        if not group_id:
            return self.root
        entry = self.resolve(group_id)
        if not entry.subgroup:
            raise ValueError(f"Entry {group_id} is not a group")
        return entry.subgroup

    def create(self, options: Dict[str, Any], parent_id: Optional[str] = None, position: Optional[int] = None) -> str:
        """Create an entry in root group or nested group."""
        group = self.resolve_group(parent_id)
        eid = group.create(options)
        entry = self.resolve(eid)
        if position is not None and position < len(group.data):
            group.data.insert(position, entry.options)
        else:
            group.data.append(entry.options)
        self.write()
        return eid

    def remove(self, entry_id: str) -> None:
        """Stop and remove an entry from its parent group."""
        entry = self.resolve(entry_id)
        entry.parent.remove(entry_id)
        self.write()

    def update(self, entry_id: str, options: Dict[str, Any], parent_id: Optional[str] = None, position: Optional[int] = None) -> None:
        """Update an entry and optionally move it to another group with rollback on failure."""
        entry = self.resolve(entry_id)
        source = entry.parent
        source_index = source.data.index(entry.options) if entry.options in source.data else -1
        target = source

        if parent_id is not None:
            target = self.resolve_group(parent_id)
            source.unlink(entry.options)
            if position is not None and position < len(target.data):
                target.data.insert(position, entry.options)
            else:
                target.data.append(entry.options)
            entry.parent = target

        try:
            entry.update(options, create=False, force=True)
        except Exception as e:
            if parent_id is not None:
                target.unlink(entry.options)
                if source_index >= 0:
                    source.data.insert(source_index, entry.options)
                else:
                    source.data.append(entry.options)
                entry.parent = source
                try:
                    entry.update({}, create=False, force=True)
                except Exception as rollback_err:
                    if self.ctx and hasattr(self.ctx, "logger"):
                        self.ctx.logger("loader").error("Rollback failed for entry %s: %s", entry_id, rollback_err)
                    else:
                        sys.stderr.write(f"[Cordis Loader Error] Rollback failed for entry {entry_id}: {rollback_err}\n")
            raise e

        source.tree.write()
        if target != source:
            target.tree.write()

    def write(self) -> None:
        """Persist tree state. In-memory trees may implement this as a no-op."""
        pass


class EntryGroup:
    """Runtime owner for a list of child loader entries matching TS EntryGroup."""

    def __init__(self, ctx: Context, tree: EntryTree):
        self.ctx = ctx
        self.tree = tree
        self.data: List[Dict[str, Any]] = []
        entry = getattr(getattr(ctx, "fiber", None), "entry", None)
        if entry:
            entry.subgroup = self

    def create(self, options: Dict[str, Any]) -> str:
        eid = self.tree.ensure_id(options)
        existing = self.tree.store.get(eid)
        loader_svc = self.ctx.get("loader") if hasattr(self.ctx, "get") else None
        entry = existing or Entry(loader=loader_svc or self.tree, name=options.get("name", eid), entry_id=eid)
        self.tree.store[eid] = entry
        prev_parent = entry.parent
        entry.parent = self

        try:
            entry.update(options, create=True, force=True)
        except Exception as e:
            if existing:
                entry.parent = prev_parent
            else:
                self.tree.store.pop(eid, None)
            raise e
        return entry.id

    def unlink(self, options: Dict[str, Any]) -> None:
        if options in self.data:
            self.data.remove(options)

    def remove(self, entry_id: str, is_dispose: bool = False) -> None:
        entry = self.tree.store.get(entry_id)
        if not entry:
            return
        entry._dispose()
        if not is_dispose:
            self.unlink(entry.options)
        self.tree.store.pop(entry_id, None)

    def update(self, config_list: List[Dict[str, Any]]) -> None:
        old_config = list(self.data)
        seen: Set[str] = set()
        for opt in config_list:
            eid = self.tree.ensure_id(opt)
            if eid in seen:
                raise ValueError(f"Duplicate loader entry id: {eid}")
            seen.add(eid)

        old_map = {opt["id"]: opt for opt in old_config if "id" in opt}
        new_map = {opt["id"]: opt for opt in config_list if "id" in opt}

        try:
            for opt in config_list:
                self.create(opt)
            for eid in list(old_map.keys()):
                if eid not in new_map:
                    self.remove(eid, is_dispose=True)
            self.data = config_list
        except Exception as e:
            # Rollback newly added
            for eid in reversed(list(new_map.keys())):
                if eid not in old_map:
                    try:
                        self.remove(eid, is_dispose=True)
                    except Exception:
                        pass
            # Restore old
            for opt in old_config:
                try:
                    self.create(opt)
                except Exception:
                    pass
            self.data = old_config
            raise e

    def stop(self) -> None:
        for opt in list(self.data):
            eid = opt.get("id")
            if eid:
                self.remove(eid, is_dispose=True)


class Entry:
    """Represents a configured plugin entry inside an EntryTree matching TS Entry."""

    def __init__(
        self,
        loader: Any,
        name: str = "",
        config: Optional[Dict[str, Any]] = None,
        disabled: bool = False,
        entry_id: Optional[str] = None,
        group: bool = False,
    ):
        self.loader = loader
        self.name = name
        self.config = config or {}
        self.id = entry_id or name or hex(random.randint(0x10000000, 0xFFFFFFFF))[2:]
        self.options: Dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "config": self.config,
            "group": group,
            "disabled": disabled,
        }
        self.fiber: Optional[Fiber] = None
        self.parent: Optional[EntryGroup] = None
        self.subgroup: Optional[EntryGroup] = None
        self.subtree: Optional[EntryTree] = None
        self._init_task: Optional[asyncio.Future] = None
        self._disposing = 0

    @property
    def disabled(self) -> bool:
        dis = self.options.get("disabled", False)
        return eval_condition(dis)

    def _dispose(self) -> None:
        if not self.fiber:
            return
        fiber = self.fiber
        self.fiber = None
        self._disposing += 1
        try:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(fiber.dispose())
            except RuntimeError:
                asyncio.run(fiber.dispose())
        finally:
            self._disposing -= 1

    def update(self, options: Dict[str, Any], create: bool = False, force: bool = False) -> None:
        """Merge new options, restart as needed, and update fiber."""
        prev = dict(self.options)
        self.options.update(options)
        self.name = self.options.get("name", self.name)
        self.config = self.options.get("config", self.config)

        if self.disabled:
            if self.fiber:
                self._dispose()
            return

        if not self.fiber:
            self.init()
        else:
            if "config" in options and self.fiber:
                self.fiber.update(self.config, no_save=True)

    def init(self) -> None:
        """Start plugin fiber."""
        if not self.loader:
            return
        plugin_cls = getattr(self.loader, "registry_map", {}).get(self.name)
        ctx = getattr(self.loader, "ctx", None)
        if not ctx:
            return

        if plugin_cls:
            if isinstance(plugin_cls, type) and issubclass(plugin_cls, Plugin):
                inst = plugin_cls(config=self.config)
                inst.id = self.id
                self.fiber = ctx.registry.plugin(inst, config=self.config)
            elif callable(plugin_cls):
                self.fiber = ctx.registry.plugin(plugin_cls, config=self.config)
            else:
                self.fiber = ctx.registry.plugin(plugin_cls, config=self.config)


# Backward compatibility aliases
EntryNode = Entry


class Loader(EntryTree, Service):
    """
    Service that owns a loader entry tree and imports configured plugins.
    Registered on ctx.loader.
    """

    name = "loader"

    def __init__(self, ctx: Optional[Context] = None, config: Optional[Dict[str, Any]] = None):
        if ctx is not None:
            Service.__init__(self, ctx, name="loader")
            EntryTree.__init__(self, ctx)
        else:
            self.ctx = None
            self.store = {}
            self.root = None
        self.config = config or {}
        self.registry_map: Dict[str, Any] = {}
        self.entries_list: List[Entry] = []

        if self.ctx:
            self.ctx.on("internal/config", self._on_internal_config)
            self.ctx.on("internal/update", self._on_internal_update)

    @property
    def entries(self) -> List[Entry]:
        """Backward compatibility list of entries."""
        if self.store:
            return list(self.store.values())
        return self.entries_list

    def _on_internal_config(self, fiber: Any, config: Any, next_fn: Any) -> Any:
        return next_fn(config)

    def _on_internal_update(self, fiber: Any, config: Any, no_save: bool, next_fn: Any) -> Any:
        return next_fn(config)

    def register_plugin_class(self, name_or_id: str, plugin_cls: Any) -> None:
        """
        Register a plugin class mapping (e.g., '@deepseek-ai/dsh-persona' -> PersonaPlugin).
        """
        self.registry_map[name_or_id] = plugin_cls

    register_plugin = register_plugin_class

    def load_from_dict(
        self,
        config_items: List[Dict[str, Any]],
        target_ctx: Optional[Context] = None,
        patches: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Load list of plugin configuration dicts onto context with optional patches.
        """
        ctx = target_ctx or self.ctx
        if not ctx:
            raise RuntimeError("Cannot load plugins without a target Context")

        items = apply_entry_patches(config_items, patches) if patches else config_items

        for item in items:
            plugin_name = item.get("name") or item.get("id")
            plugin_id = item.get("id", plugin_name)
            is_group = item.get("group", False) or plugin_name == "cordis:group"
            disabled_cond = item.get("disabled", False)

            is_disabled = eval_condition(disabled_cond)
            entry = Entry(
                loader=self,
                name=plugin_name,
                config=item.get("config"),
                disabled=is_disabled,
                entry_id=plugin_id,
                group=is_group
            )
            if self.store is not None:
                self.store[entry.id] = entry
            self.entries_list.append(entry)

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
                    if ctx and hasattr(ctx, "logger"):
                        ctx.logger("loader").warn("Registered item '%s' is not a valid plugin", plugin_name)
                    else:
                        sys.stderr.write(f"[Cordis Loader Warning] Registered item '{plugin_name}' is not a valid plugin\n")
                entry.fiber = fiber
            else:
                if ctx and hasattr(ctx, "logger"):
                    ctx.logger("loader").warn("Unknown plugin name/id: '%s'", plugin_name)
                else:
                    sys.stderr.write(f"[Cordis Loader Warning] Unknown plugin name/id: '{plugin_name}'\n")

    def load_preset_file(
        self,
        filepath: str,
        target_ctx: Optional[Context] = None,
        patches: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        Load preset YAML file and mount onto context with optional patches.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Preset file not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, list):
            self.load_from_dict(data, target_ctx, patches=patches)
        elif isinstance(data, dict) and "plugins" in data:
            self.load_from_dict(data["plugins"], target_ctx, patches=patches)
        else:
            raise ValueError(f"Invalid preset format in {filepath}")


# Backward compatibility alias
PresetLoader = Loader
