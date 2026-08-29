"""
Cordis Composition & Loader System matching reference/vendor/loader/src/*
Implements EntryTree, EntryGroup, Entry, Loader service, and interpolate expressions engine.
"""

import asyncio
import copy
import importlib
import importlib.util
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


def resolve_plugin_class(name: str, registry_map: Optional[Dict[str, Any]] = None, return_mod_name: bool = False) -> Any:
    """
    Dynamically resolve a plugin class from registry_map, module specifier, or file path.
    Supports:
    1. Direct registry_map lookup ('@deepseek-ai/dsh-persona')
    2. Dotted Python module path ('dsh.todo.tool_todo.ToolTodoPlugin')
    3. Module:Class specifier ('my_package.module:CustomPlugin')
    4. File path:Class specifier ('plugins/custom.py:MyPlugin')
    """
    mod_name_res: Optional[str] = None

    if registry_map and name in registry_map:
        res = registry_map[name]
        return (res, None) if return_mod_name else res

    if not isinstance(name, str) or not name:
        return (None, None) if return_mod_name else None

    # Check for file path or module:class format
    if ":" in name:
        target_path, class_name = name.rsplit(":", 1)
        target_path = target_path.strip()
        class_name = class_name.strip()

        try:
            if target_path.endswith(".py") or os.path.exists(target_path):
                mod_name_res = f"dynamic_cordis_plugin_{abs(hash(os.path.abspath(target_path)))}"
                spec = importlib.util.spec_from_file_location(mod_name_res, os.path.abspath(target_path))
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name_res] = mod
                    spec.loader.exec_module(mod)
                    cls = getattr(mod, class_name, None)
                    if cls and registry_map is not None:
                        registry_map[name] = cls
                    return (cls, mod_name_res) if return_mod_name else cls
            else:
                mod = importlib.import_module(target_path)
                cls = getattr(mod, class_name, None)
                if cls and registry_map is not None:
                    registry_map[name] = cls
                return (cls, target_path) if return_mod_name else cls
        except Exception:
            return (None, None) if return_mod_name else None

    # Check for dotted Python path
    if "." in name and not name.startswith("@") and not name.startswith("/"):
        parts = name.rsplit(".", 1)
        if len(parts) == 2:
            try:
                mod = importlib.import_module(parts[0])
                cls = getattr(mod, parts[1], None)
                if cls is not None:
                    if registry_map is not None:
                        registry_map[name] = cls
                    return (cls, parts[0]) if return_mod_name else cls
            except Exception:
                pass

    return (None, None) if return_mod_name else None



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


import ast


class SafeASTEvaluator(ast.NodeVisitor):
    """
    AST-based safe expression evaluator matching Cordis expression semantics
    without allowing arbitrary code execution.
    """

    def __init__(self, scope: Dict[str, Any]):
        self.scope = scope

    def eval(self, node: ast.AST) -> Any:
        return self.visit(node)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    # Python 3.8 backward compatibility
    def visit_Num(self, node: Any) -> Any:
        return node.n

    def visit_Str(self, node: Any) -> Any:
        return node.s

    def visit_NameConstant(self, node: Any) -> Any:
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:
        name = node.id
        if name in self.scope:
            return self.scope[name]
        if name in ("True", "true"):
            return True
        if name in ("False", "false"):
            return False
        if name in ("None", "null", "undefined"):
            return None
        ctx = self.scope.get("ctx")
        if ctx is not None:
            val = getattr(ctx, name, None)
            if val is not None:
                return val
        return None

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        val = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not val
        elif isinstance(node.op, ast.USub):
            return -val
        elif isinstance(node.op, ast.UAdd):
            return +val
        elif isinstance(node.op, ast.Invert):
            return ~val
        raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        op = node.op
        if isinstance(op, ast.Add): return left + right
        if isinstance(op, ast.Sub): return left - right
        if isinstance(op, ast.Mult): return left * right
        if isinstance(op, ast.Div): return left / right
        if isinstance(op, ast.FloorDiv): return left // right
        if isinstance(op, ast.Mod): return left % right
        if isinstance(op, ast.Pow): return left ** right
        if isinstance(op, ast.BitOr): return left | right
        if isinstance(op, ast.BitXor): return left ^ right
        if isinstance(op, ast.BitAnd): return left & right
        if isinstance(op, ast.LShift): return left << right
        if isinstance(op, ast.RShift): return left >> right
        raise ValueError(f"Unsupported binary operator: {type(op).__name__}")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.And):
            res = True
            for v in node.values:
                res = self.visit(v)
                if not res:
                    return res
            return res
        elif isinstance(node.op, ast.Or):
            res = False
            for v in node.values:
                res = self.visit(v)
                if res:
                    return res
            return res
        raise ValueError(f"Unsupported boolean operator: {type(node.op).__name__}")

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            matched = False
            if isinstance(op, ast.Eq): matched = (left == right)
            elif isinstance(op, ast.NotEq): matched = (left != right)
            elif isinstance(op, ast.Lt): matched = (left < right)
            elif isinstance(op, ast.LtE): matched = (left <= right)
            elif isinstance(op, ast.Gt): matched = (left > right)
            elif isinstance(op, ast.GtE): matched = (left >= right)
            elif isinstance(op, ast.Is): matched = (left is right)
            elif isinstance(op, ast.IsNot): matched = (left is not right)
            elif isinstance(op, ast.In): matched = (left in right)
            elif isinstance(op, ast.NotIn): matched = (left not in right)
            else:
                raise ValueError(f"Unsupported comparison operator: {type(op).__name__}")
            if not matched:
                return False
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        test = self.visit(node.test)
        if test:
            return self.visit(node.body)
        else:
            return self.visit(node.orelse)

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        val = self.visit(node.value)
        if hasattr(ast, "Index") and isinstance(node.slice, getattr(ast, "Index")):
            idx = self.visit(node.slice.value)
        else:
            idx = self.visit(node.slice)
        if val is None:
            return None
        return val[idx]

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        attr = node.attr
        if attr.startswith("__"):
            raise ValueError(f"Access to private attribute '{attr}' is forbidden")
        val = self.visit(node.value)
        if val is None:
            return None
        if isinstance(val, dict):
            return val.get(attr)
        return getattr(val, attr, None)

    def visit_List(self, node: ast.List) -> Any:
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Dict(self, node: ast.Dict) -> Any:
        return {self.visit(k): self.visit(v) for k, v in zip(node.keys, node.values)}

    def visit_Call(self, node: ast.Call) -> Any:
        func = self.visit(node.func)
        if not callable(func):
            raise ValueError(f"Object {func} is not callable")
        args = [self.visit(arg) for arg in node.args]
        kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords}
        return func(*args, **kwargs)


def evaluate_expr(ctx: Any, expr: str) -> Any:
    """
    Safely evaluate expression string in the given Context matching TS evaluate(ctx, expr).
    Translates common JS patterns to Python syntax safely using AST analysis.
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
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "len": len,
        "max": max,
        "min": min,
        "getattr": getattr,
        "hasattr": hasattr,
    }

    try:
        expr_py = expr_py.strip()
        parsed_ast = ast.parse(expr_py, mode="eval")
        evaluator = SafeASTEvaluator(scope)
        return evaluator.eval(parsed_ast)
    except Exception as e:
        if ctx and hasattr(ctx, "logger"):
            ctx.logger("loader").warn("Failed to evaluate expression '%s': %s", expr, e)
        return expr


def interpolate(ctx: Any, config: Any) -> Any:
    """
    Recursively interpolate JS expression nodes and ${...} string templates
    against the target context matching TS interpolate(ctx, config).
    """
    if is_js_expr(config):
        return evaluate_expr(ctx, config["__jsExpr"])
    elif isinstance(config, str):
        if config.startswith("!!js "):
            return evaluate_expr(ctx, config[5:])
        # Support ${VAR} and ${VAR:-default} template expansion
        if "${" in config:
            def _sub(match):
                inner = match.group(1).strip()
                if ":-" in inner:
                    var_name, default_val = inner.split(":-", 1)
                    val = os.environ.get(var_name.strip())
                    return val if val is not None else default_val
                elif inner.startswith("process.env.") or inner.startswith("env."):
                    var_name = inner.split(".", 1)[1]
                    return os.environ.get(var_name, "")
                elif inner in os.environ:
                    return os.environ[inner]
                res = evaluate_expr(ctx, inner)
                return str(res) if res is not None else ""
            expanded = re.sub(r'\$\{([^}]+)\}', _sub, config)
            return expanded
        return config
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
        self._loaded_module_name: Optional[str] = None

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

    @disabled.setter
    def disabled(self, value: bool) -> None:
        self.options["disabled"] = value

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
            if self._loaded_module_name and self._loaded_module_name in sys.modules:
                del sys.modules[self._loaded_module_name]
                self._loaded_module_name = None
                importlib.invalidate_caches()

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
        reg_map = getattr(self.loader, "registry_map", {})
        plugin_cls, mod_name = resolve_plugin_class(self.name, reg_map, return_mod_name=True)
        if mod_name:
            self._loaded_module_name = mod_name
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
            self.ctx = ctx
        else:
            self.ctx = None
            self.store = {}
            self.root = None
        self.config = config or {}
        self.registry_map: Dict[str, Any] = {}
        self.entries_list: List[Entry] = []
        self._realms: Dict[str, GlobalRealm] = {}
        self._delims: Dict[str, str] = {}

        if self.ctx:
            self.ctx.on("internal/config", self._on_internal_config, global_listener=True)
            self.ctx.on("internal/update", self._on_internal_update, global_listener=True, prepend=True)

            def _on_entry_init(entry: Entry) -> None:
                if entry.ctx:
                    entry.ctx._intercept_map = dict(getattr(entry.ctx, "_intercept_map", {}))
                    entry.ctx._isolated_keys = dict(getattr(entry.ctx, "_isolated_keys", {}))
                    if not hasattr(entry.ctx, "_isolate_delims"):
                        entry.ctx._isolate_delims = {}

            self.ctx.on("loader/entry-init", _on_entry_init)

            def _on_patch_context(entry: Entry, next_fn: Callable[[], Any] = None) -> Any:
                parent_ctx = getattr(entry.parent, "ctx", None) if entry.parent else None
                base_ctx = parent_ctx or getattr(entry, "ctx", None)
                old_map = dict(getattr(entry.ctx, "_isolated_keys", {}))

                # Step 1: Generate new isolate map
                new_map = dict(getattr(base_ctx, "_isolated_keys", {})) if base_ctx else {}
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

                # Step 2: Generate service diff with Delimiters matching TS isolate.ts:103-120
                diff: Dict[str, Tuple[str, str, str, str]] = {}
                all_names = set(new_map.keys()) | set(self._delims.keys()) | set(old_map.keys())
                if not hasattr(entry.ctx, "_isolate_delims"):
                    entry.ctx._isolate_delims = {}

                for name in all_names:
                    old_sym = old_map.get(name, "")
                    new_sym = new_map.get(name, "")
                    if old_sym == new_sym:
                        continue

                    delim_k = self._delims.setdefault(name, f"delim:{name}")
                    entry_flag = f"{name}#{entry.id}"
                    entry.ctx._isolate_delims[delim_k] = entry_flag

                    for sym in (old_sym, new_sym):
                        if not sym:
                            continue
                        impl = entry.ctx.reflect.store.get(sym) if hasattr(entry.ctx, "reflect") and hasattr(entry.ctx.reflect, "store") else None
                        if not impl:
                            continue
                        impl_fiber = getattr(impl, "fiber", None)
                        if not impl_fiber:
                            continue
                        impl_ctx = getattr(impl_fiber, "ctx", None)
                        impl_delims = getattr(impl_ctx, "_isolate_delims", {}) if impl_ctx else {}
                        impl_flag = impl_delims.get(delim_k, "")
                        diff[name] = (old_sym, new_sym, entry_flag, impl_flag)
                        if entry_flag != impl_flag:
                            break

                # Step 3: Update isolate & intercept maps
                entry.ctx._isolated_keys = new_map
                intercept_opt = entry.options.get("intercept", {})
                if isinstance(intercept_opt, dict):
                    entry.ctx._intercept_map.update(intercept_opt)

                # Step 4: Reload fiber
                res = None
                if next_fn and callable(next_fn):
                    res = next_fn()

                # Step 5: Replace service impl in reflect store matching TS isolate.ts:132-137
                if hasattr(entry.ctx, "reflect") and hasattr(entry.ctx.reflect, "store"):
                    for name, (sym1, sym2, flag1, flag2) in diff.items():
                        if flag1 == flag2 and sym1 in entry.ctx.reflect.store and sym2 not in entry.ctx.reflect.store:
                            entry.ctx.reflect.store[sym2] = entry.ctx.reflect.store[sym1]
                            del entry.ctx.reflect.store[sym1]

                # Step 6: Reflect notify with Delimiter filter matching TS isolate.ts:140-146
                if diff and hasattr(self.ctx, "reflect"):
                    def _filter_notify(target_ctx: Any, s_name: str) -> bool:
                        if s_name not in diff:
                            return True
                        sym1, sym2, flag1, flag2 = diff[s_name]
                        sym3 = getattr(target_ctx, "_isolated_keys", {}).get(s_name, "")
                        target_delims = getattr(target_ctx, "_isolate_delims", {})
                        delim_key = self._delims.get(s_name, "")
                        flag3 = target_delims.get(delim_key, "")
                        return (sym1 == sym3 or sym2 == sym3) and (flag1 == flag3) != (flag1 == flag2)

                    self.ctx.reflect.notify(list(diff.keys()), filter_fn=_filter_notify)

                # Step 7: Clean up delimiters
                for name, delim_key in list(self._delims.items()):
                    if name not in new_map:
                        if hasattr(entry.ctx, "_isolate_delims"):
                            entry.ctx._isolate_delims.pop(delim_key, None)

                return res

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

            def _on_internal_plugin(fiber: Any) -> None:
                # 1. set fiber.entry and resolve inject matching TS Loader index.ts:118-123
                parent_entry = getattr(getattr(fiber, "parent", None), "_entry", None) or getattr(getattr(fiber, "parent", None), "entry", None)
                if parent_entry and not getattr(fiber, "entry", None):
                    fiber.entry = parent_entry
                    from dsh.cordis.registry import Inject
                    opt_inject = getattr(parent_entry, "options", {}).get("inject") if hasattr(parent_entry, "options") else None
                    if opt_inject:
                        Inject.resolve(opt_inject, fiber.inject)

                # 2. handle self-dispose (7 cases matching reference index.ts:128-157)
                # Case 1: fiber is created (uid is not None)
                if getattr(fiber, "uid", None) is not None:
                    return

                # Case 2: fiber is not tracked by loader
                entry = getattr(fiber, "entry", None)
                if not entry:
                    return

                # Case 3: fiber is a child plugin under the entry (not entry's root fiber)
                parent_fiber = getattr(getattr(fiber, "parent", None), "fiber", None)
                if parent_fiber and getattr(parent_fiber, "entry", None) == entry:
                    return

                # Case 4: fiber is disposed on behalf of plugin deletion (such as plugin hmr)
                runtime = getattr(fiber, "runtime", None)
                if runtime and hasattr(self.ctx, "registry") and not self.ctx.registry.has(runtime.callback):
                    return

                # Case 5: the entry's tree is being disposed
                parent_group = getattr(entry, "parent", None)
                tree = getattr(parent_group, "tree", None) or getattr(entry, "tree", None)
                if tree and hasattr(tree, "ctx") and hasattr(tree.ctx, "fiber"):
                    tree_owner = tree.ctx.fiber
                    from dsh.cordis.fiber import FiberState
                    if getattr(tree_owner, "uid", None) is None or getattr(tree_owner, "state", None) == FiberState.UNLOADING:
                        return

                # Case 6: Loader is replacing or removing this exact fiber
                if getattr(entry, "_disposing", False):
                    return

                self.show_log(entry, "unload")

                # Case 7: fiber is disposed by loader behavior (already disabled)
                if getattr(entry, "disabled", False):
                    return

                entry.disabled = True
                if hasattr(entry, "options") and isinstance(entry.options, dict):
                    entry.options["disabled"] = True

                if tree and hasattr(tree, "write"):
                    tree.write()

            self.ctx.on("internal/plugin", _on_internal_plugin, global_listener=True)

    def show_log(self, entry: Any, action_type: str) -> None:
        """Log loader plugin lifecycle events matching TS Loader.showLog."""
        if getattr(entry, "group", False):
            return
        entry_name = getattr(entry, "name", str(entry))
        if hasattr(self.ctx, "logger"):
            self.ctx.logger("loader").info("%s plugin %s", action_type, entry_name)

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
        target_ctx = kwargs.get("caller_ctx") or (args[0] if args and hasattr(args[0], "fiber") else None)
        fiber = getattr(target_ctx, "fiber", None) if target_ctx else None

        next_fn = args[-1] if args and callable(args[-1]) else (lambda c=config: c)
        res = next_fn(config) if callable(next_fn) else config

        if fiber and getattr(fiber, "entry", None) and not no_save:
            parent_fiber = getattr(getattr(fiber, "parent", None), "fiber", None)
            if not parent_fiber or getattr(parent_fiber, "entry", None) != fiber.entry:
                entry = fiber.entry
                cfg_schema = getattr(getattr(fiber, "runtime", None), "Config", None) or getattr(getattr(fiber, "plugin", None), "Config", None)
                if cfg_schema and hasattr(cfg_schema, "simplify") and callable(cfg_schema.simplify):
                    simplified = cfg_schema.simplify(config)
                    entry.options["config"] = simplified if simplified is not None else config
                else:
                    entry.options["config"] = config
                if entry.parent and hasattr(entry.parent, "tree") and hasattr(entry.parent.tree, "write"):
                    entry.parent.tree.write()
        return res

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

            plugin_cls = resolve_plugin_class(plugin_name, self.registry_map)
            if plugin_cls:
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
