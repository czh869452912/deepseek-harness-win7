"""
Cordis Composition & Loader System matching reference/vendor/loader/src/*
Implements EntryTree, EntryGroup, Entry, Loader service, and interpolate expressions engine.
"""

import asyncio
import copy
import os
import platform
import random
import re
import sys
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union
import yaml

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


def js_constructor(loader: Any, node: Any) -> Dict[str, str]:
    return {"__jsExpr": loader.construct_scalar(node)}


try:
    yaml.SafeLoader.add_constructor('tag:yaml.org,2002:js', js_constructor)
    yaml.SafeLoader.add_constructor('!!js', js_constructor)
except Exception:
    pass


def is_js_expr(value: Any) -> bool:
    """Return whether a value is a JS expression node matching TS isJsExpr."""
    return isinstance(value, dict) and "__jsExpr" in value and isinstance(value["__jsExpr"], str)


def evaluate_expr(ctx: Any, expr: str) -> Any:
    """
    Safely evaluate expression string in the given Context matching TS evaluate(ctx, expr).
    Translates common JS patterns to Python syntax safely including ternary and logical operators.
    """
    expr_str = expr.strip()
    if expr_str.startswith("!!js"):
        expr_str = expr_str[4:].strip()

    # 1. Normalize JS boolean and comparison operators to Python
    expr_py = expr_str
    expr_py = re.sub(r'===', '==', expr_py)
    expr_py = re.sub(r'!==', '!=', expr_py)
    expr_py = re.sub(r'&&', ' and ', expr_py)
    expr_py = re.sub(r'\|\|', ' or ', expr_py)
    expr_py = re.sub(r'!(?!=)', ' not ', expr_py)
    expr_py = re.sub(r'\btrue\b', 'True', expr_py)
    expr_py = re.sub(r'\bfalse\b', 'False', expr_py)
    expr_py = re.sub(r'\bnull\b', 'None', expr_py)
    expr_py = re.sub(r'\bundefined\b', 'None', expr_py)
    expr_py = expr_py.replace("process.platform", "sys.platform")
    expr_py = re.sub(r'process\.env\.([A-Za-z0-9_]+)', r'env.get("\1")', expr_py)
    expr_py = re.sub(r'process\.env\[(["\'])([A-Za-z0-9_]+)\1\]', r'env.get("\2")', expr_py)
    expr_py = expr_py.replace("process.env", "env")

    # 2. Handle JS ternary expressions `cond ? val1 : val2` -> `(val1 if cond else val2)`
    ternary_re = re.compile(r'([^\?:]+)\?([^\?:]+):([^\?:]+)')
    while ternary_re.search(expr_py):
        expr_py = ternary_re.sub(r'(\2 if \1 else \3)', expr_py)

    scope = {
        "ctx": ctx,
        "env": os.environ,
        "sys": sys,
        "os": os,
        "platform": platform,
    }
    try:
        return eval(expr_py, {"__builtins__": {}}, scope)
    except Exception as e:
        if ctx and hasattr(ctx, "logger"):
            ctx.logger("loader").warn("Failed to evaluate expression '%s': %s", expr, e)
        return expr


def interpolate(ctx: Any, config: Any) -> Any:
    """
    Recursively interpolate JS expression nodes against the target context
    matching TS interpolate(ctx, config).
    """
    if is_js_expr(config):
        return evaluate_expr(ctx, config["__jsExpr"])
    elif isinstance(config, str) and config.startswith("!!js "):
        return evaluate_expr(ctx, config[5:])
    elif isinstance(config, list):
        return [interpolate(ctx, item) for item in config]
    elif isinstance(config, dict):
        return {k: interpolate(ctx, v) for k, v in config.items()}
    return config


def eval_condition(condition: Any, ctx: Optional[Any] = None) -> bool:
    """
    Safely evaluate boolean expression for 'disabled' or 'enabled' fields in plugin configs.
    Example: sys.platform == 'win32' or platform.system() == 'Windows'
    """
    if not condition:
        return False
    if isinstance(condition, bool):
        return condition

    if is_js_expr(condition):
        return bool(evaluate_expr(ctx, condition["__jsExpr"]))

    cond_str = str(condition).strip()
    if cond_str.startswith("!!js"):
        return bool(evaluate_expr(ctx, cond_str[4:].strip()))

    return bool(evaluate_expr(ctx, cond_str))


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


def sort_keys(data: Dict[str, Any], prepend: Tuple[str, ...] = ("id", "name"), append: Tuple[str, ...] = ("config",)) -> Dict[str, Any]:
    """Sort dictionary keys matching TS sortKeys(object, prepend=['id', 'name'], append=['config'])."""
    result: Dict[str, Any] = {}
    for k in prepend:
        if k in data:
            result[k] = data[k]
    middle_keys = sorted([k for k in data.keys() if k not in prepend and k not in append])
    for k in middle_keys:
        result[k] = data[k]
    for k in append:
        if k in data:
            result[k] = data[k]
    return result


class Realm:
    """Symbol realm used to isolate service implementations by entry or label matching reference/vendor/loader/src/config/isolate.ts."""
    def __init__(self):
        self.store: Dict[str, str] = {}

    @property
    def suffix(self) -> str:
        raise NotImplementedError

    def access(self, key: str, create: bool = False) -> str:
        if create:
            if key not in self.store:
                self.store[key] = f"{key}{self.suffix}"
            return self.store[key]
        return self.store.get(key, f"{key}{self.suffix}")

    def delete(self, key: str) -> None:
        self.store.pop(key, None)

    @property
    def size(self) -> int:
        return len(self.store)


class LocalRealm(Realm):
    """Entry-local isolation realm matching TS LocalRealm."""
    def __init__(self, entry: "Entry"):
        super().__init__()
        self.entry = entry

    @property
    def suffix(self) -> str:
        return f"#{getattr(self.entry, 'id', 'local')}"


class GlobalRealm(Realm):
    """Named isolation realm shared by entries that use the same label matching TS GlobalRealm."""
    def __init__(self, label: str):
        super().__init__()
        self.label = label

    @property
    def suffix(self) -> str:
        return f"@{self.label}"


class EntryTree:
    """
    Mutable tree of loader entries matching reference/vendor/loader/src/config/tree.ts.
    Persistence is supplied by subclasses or write() implementations.
    """
    sep = ":"

    def __init__(self, ctx: Context, filepath: Optional[str] = None):
        self.ctx = ctx.extend()
        self.enable_logs = True
        self.filepath = filepath
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
            if entry.options in group.data:
                group.data.remove(entry.options)
            group.data.insert(position, entry.options)
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

    def write(self) -> None:
        """Persist tree state. If filepath is set, writes out YAML atomically matching TS EntryTree.write()."""
        if not getattr(self, "filepath", None):
            return
        try:
            sorted_data = [sort_keys(dict(opt)) for opt in self.root.data]
            with open(self.filepath, "w", encoding="utf-8") as f:
                yaml.safe_dump(sorted_data, f, sort_keys=False, allow_unicode=True)
        except Exception as e:
            if self.ctx and hasattr(self.ctx, "logger"):
                self.ctx.logger("loader").error("Failed to write EntryTree to %s: %s", self.filepath, e)
            else:
                sys.stderr.write(f"[Cordis Loader Error] Failed to write EntryTree to {self.filepath}: {e}\n")


class EntryGroup:
    """Runtime owner for a list of child loader entries matching TS EntryGroup."""
    key = "cordis.entryGroup"

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
        is_group = options.get("group", False) or options.get("name") == "cordis:group"
        entry = existing or Entry(loader=loader_svc or self.tree, name=options.get("name", eid), entry_id=eid, group=is_group)
        if is_group and not entry.subgroup:
            entry.subgroup = EntryGroup(entry.ctx, self.tree)
        self.tree.store[eid] = entry
        prev_parent = entry.parent
        entry.parent = self

        try:
            entry.update(options, create=True, force=True)
            if entry.options not in self.data:
                self.data.append(entry.options)
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
    key = "cordis.entry"

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

        loader_ctx = getattr(loader, "ctx", None) if loader else None
        if loader_ctx:
            self.ctx = loader_ctx.extend({"entry": self})
            self.ctx.emit("loader/entry-init", self)
        else:
            self.ctx = Context()

        if group or self.options.get("group") or self.name == "cordis:group":
            tree_obj = getattr(loader, "tree", loader) if loader else None
            self.subgroup = EntryGroup(self.ctx, tree_obj)

    @property
    def disabled(self) -> bool:
        dis = self.options.get("disabled", False)
        return eval_condition(dis, self.ctx)

    def get_outer_stack(self) -> List[str]:
        """Build virtual diagnostic stack tracing entry configuration locations."""
        entry: Optional[Entry] = self
        res: List[str] = []
        while entry is not None:
            base_url = getattr(getattr(entry.parent, "tree", None), "filepath", None) or getattr(getattr(entry.ctx, "root", None), "base_url", "root")
            res.append(f"    at {base_url}#{getattr(entry, 'id', 'anonymous')}")
            parent_ctx = getattr(entry.parent, "ctx", None) if entry.parent else None
            entry = getattr(getattr(parent_ctx, "fiber", None), "entry", None) if parent_ctx else None
        return res

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
            if self.fiber and self.fiber.error is not None:
                raise self.fiber.error
        else:
            if "config" in options and self.fiber:
                self.fiber.update(self.config, no_save=True)
                if self.fiber.error is not None:
                    raise self.fiber.error

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
                self.fiber = ctx.registry.plugin(inst, config=self.config, get_outer_stack=self.get_outer_stack)
            elif callable(plugin_cls):
                self.fiber = ctx.registry.plugin(plugin_cls, config=self.config, get_outer_stack=self.get_outer_stack)
            else:
                self.fiber = ctx.registry.plugin(plugin_cls, config=self.config, get_outer_stack=self.get_outer_stack)
            if self.fiber:
                self.fiber.entry = self


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
        self._realms: Dict[str, GlobalRealm] = {}

        if self.ctx:
            self.ctx.on("internal/config", self._on_internal_config)
            self.ctx.on("internal/update", self._on_internal_update)

            def _on_entry_init(entry: Entry) -> None:
                if entry.ctx:
                    entry.ctx._intercept_map = dict(getattr(entry.ctx, "_intercept_map", {}))
                    entry.ctx._isolated_keys = dict(getattr(entry.ctx, "_isolated_keys", {}))

            self.ctx.on("loader/entry-init", _on_entry_init)

            def _on_patch_context(entry: Entry, next_fn: Callable[[], Any] = None) -> Any:
                new_map = dict(getattr(entry.parent.ctx, "_isolated_keys", {})) if entry.parent else {}
                isolate_opt = entry.options.get("isolate", {})
                if isinstance(isolate_opt, dict):
                    for name, label in isolate_opt.items():
                        if label is True:
                            realm = getattr(entry, "realm", None)
                            if realm is None:
                                realm = LocalRealm(entry)
                                entry.realm = realm
                            new_map[name] = realm.access(name, create=True)
                        elif isinstance(label, str):
                            realm = self._realms.get(label)
                            if realm is None:
                                realm = GlobalRealm(label)
                                self._realms[label] = realm
                            new_map[name] = realm.access(name, create=True)
                        elif label:
                            new_map[name] = str(label)
                entry.ctx._isolated_keys = new_map

                intercept_opt = entry.options.get("intercept", {})
                if isinstance(intercept_opt, dict):
                    entry.ctx._intercept_map.update(intercept_opt)

                if next_fn and callable(next_fn):
                    return next_fn()

            self.ctx.on("loader/patch-context", _on_patch_context)

            def _on_partial_dispose(entry: Entry, legacy: Dict[str, Any], active: bool) -> None:
                legacy_isolate = legacy.get("isolate") if isinstance(legacy, dict) else {}
                if isinstance(legacy_isolate, dict):
                    for name, label in legacy_isolate.items():
                        if label is True or not isinstance(label, str):
                            continue
                        if active and entry.options.get("isolate", {}).get(name) == label:
                            continue
                        realm = self._realms.get(label)
                        if not realm:
                            continue
                        in_use = any(e.options.get("isolate", {}).get(name) == label for e in self.entries if e is not entry)
                        if not in_use:
                            realm.delete(name)
                            if realm.size == 0:
                                self._realms.pop(label, None)

            self.ctx.on("loader/partial-dispose", _on_partial_dispose)

    @property
    def entries(self) -> List[Entry]:
        """Backward compatibility list of entries."""
        if self.store:
            return list(self.store.values())
        return self.entries_list

    def _on_internal_config(self, config: Any, *args: Any, **kwargs: Any) -> Any:
        target_ctx = kwargs.get("caller_ctx") or (args[0] if args and hasattr(args[0], "fiber") else None)
        fiber = getattr(target_ctx, "fiber", None) if target_ctx else None

        next_fn = args[-1] if args and callable(args[-1]) else (lambda c=config: c)
        resolved = next_fn(config) if callable(next_fn) else config

        if not fiber or not getattr(fiber, "entry", None):
            return resolved

        parent_fiber = getattr(getattr(fiber, "parent", None), "fiber", None)
        if parent_fiber and getattr(parent_fiber, "entry", None) == fiber.entry:
            return resolved

        plugin = getattr(fiber, "plugin", None) or getattr(getattr(fiber, "runtime", None), "callback", None)
        if getattr(plugin, "is_tree_carrier", False) or getattr(plugin, EntryGroup.key, False) or getattr(plugin, "group", False):
            return resolved

        return interpolate(fiber.ctx, resolved)

    def _on_internal_update(self, config: Any, no_save: bool = False, *args: Any, **kwargs: Any) -> Any:
        next_fn = args[-1] if args and callable(args[-1]) else (lambda c=config: c)
        return next_fn(config) if callable(next_fn) else config

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

            is_disabled = eval_condition(disabled_cond, ctx)
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
                    fiber = ctx.registry.plugin(plugin_instance, config=config, get_outer_stack=entry.get_outer_stack)
                elif callable(plugin_cls):
                    fiber = ctx.registry.plugin(plugin_cls, config=config, get_outer_stack=entry.get_outer_stack)
                else:
                    if ctx and hasattr(ctx, "logger"):
                        ctx.logger("loader").warn("Registered item '%s' is not a valid plugin", plugin_name)
                    else:
                        sys.stderr.write(f"[Cordis Loader Warning] Registered item '{plugin_name}' is not a valid plugin\n")
                if fiber:
                    fiber.entry = entry
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
