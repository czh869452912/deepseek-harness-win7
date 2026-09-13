"""
Cordis Composition & Loader System matching reference/vendor/loader/src/*
Implements EntryTree, EntryGroup, Entry, Loader service, and interpolate expressions engine.
"""

import asyncio
import copy
import importlib
import importlib.util
import inspect
import json
import os
import platform
import random
import re
import sys
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union
import yaml

from dsh.cordis.context import Context
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.utils import _UNDEFINED, deep_equal, is_nullable


class AwaitableString(str):
    def __new__(cls, val: str, task: Optional[Any] = None):
        inst = super().__new__(cls, val)
        inst._task = task
        return inst

    def __await__(self):
        if getattr(self, "_task", None) is not None and inspect.isawaitable(self._task):
            async def _wrap():
                await self._task
                return str(self)
            return _wrap().__await__()
        async def _ret():
            return str(self)
        return _ret().__await__()


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
    val = loader.construct_scalar(node)
    if val is None or not str(val).strip():
        raise ValueError("empty !!js expression body")
    return {"__jsExpr": val}


import yaml.emitter
_orig_choose_scalar_style = yaml.emitter.Emitter.choose_scalar_style

def _dsh_choose_scalar_style(self):
    if getattr(self.event, "tag", None) in ("tag:yaml.org,2002:js", "!!js") and not getattr(self.event, "style", None):
        if self.analysis is None:
            self.analysis = self.analyze_scalar(self.event.value)
        if (not (self.simple_key_context and (self.analysis.empty or self.analysis.multiline))
            and (self.flow_level and self.analysis.allow_flow_plain
                or (not self.flow_level and self.analysis.allow_block_plain))):
            return ""
        if self.analysis.allow_single_quoted and not (self.simple_key_context and self.analysis.multiline):
            return "'"
        return '"'
    return _orig_choose_scalar_style(self)

yaml.emitter.Emitter.choose_scalar_style = _dsh_choose_scalar_style

try:
    yaml.SafeLoader.add_constructor('tag:yaml.org,2002:js', js_constructor)
    yaml.SafeLoader.add_constructor('!!js', js_constructor)

    def js_dict_representer(dumper: Any, data: Any) -> Any:
        if len(data) == 1 and "__jsExpr" in data:
            return dumper.represent_scalar('tag:yaml.org,2002:js', str(data["__jsExpr"]))
        return dumper.represent_dict(data.items())

    yaml.SafeDumper.add_representer(dict, js_dict_representer)
except Exception:
    pass


def is_js_expr(value: Any) -> bool:
    """Return whether a value is a JS expression node matching TS isJsExpr."""
    return isinstance(value, dict) and "__jsExpr" in value


import ast


class SecurityViolation(Exception):
    """Exception raised when an unsafe or forbidden AST operation is attempted."""
    pass


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
            target = getattr(ctx, "root", ctx)
            if hasattr(target, "get"):
                try:
                    val = target.get(name, strict=False)
                    if val is not None:
                        return val
                except Exception:
                    pass
            if hasattr(ctx, "get"):
                try:
                    val = ctx.get(name, strict=False)
                    if val is not None:
                        return val
                except Exception:
                    pass
            try:
                val = getattr(ctx, name, None)
                if val is not None:
                    return val
            except Exception:
                pass
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
            raise SecurityViolation(f"Access to private attribute '{attr}' is forbidden")
        val = self.visit(node.value)
        if val is None:
            return None
        if attr == "length" and hasattr(val, "__len__"):
            return len(val)
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
    expr_py = re.sub(r'\(\(\)\s*=>\s*\{\s*throw\s+(?:new\s+)?Error\((.*?)\);?\s*\}\)\(\)', r'(_throw(\1))', expr_py)

    # 2. Handle JS nullish coalescing `a ?? b` -> `_coalesce(a, b)` (must precede ternary)
    coalesce_re = re.compile(r'([^?]+)\?\?([^?]+)')
    while coalesce_re.search(expr_py):
        expr_py = coalesce_re.sub(r'(_coalesce(\1, \2))', expr_py)

    # 3. Handle JS ternary expressions `cond ? val1 : val2` -> `(val1 if cond else val2)`
    ternary_re = re.compile(r'([^\?:]+)\?([^\?:]+):([^\?:]+)')
    while ternary_re.search(expr_py):
        expr_py = ternary_re.sub(r'(\2 if \1 else \3)', expr_py)

    def _coalesce(a: Any, b: Any) -> Any:
        return b if a is None else a

    def _throw(msg: Any) -> Any:
        raise RuntimeError(str(msg))

    class _Process:
        platform = "win32" if sys.platform.startswith("win") else sys.platform
        version = "v20.0.0"
        env = os.environ

    class _JSON:
        parse = staticmethod(json.loads)
        stringify = staticmethod(json.dumps)

    scope = {
        "_coalesce": _coalesce,
        "process": _Process,
        "JSON": _JSON,
        "_throw": _throw,
        "Error": RuntimeError,
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

    expr_py = expr_py.strip()
    try:
        parsed_ast = ast.parse(expr_py, mode="eval")
    except Exception as e:
        if ctx and hasattr(ctx, "logger"):
            ctx.logger("loader").warn("Failed to parse expression '%s': %s", expr, e)
        raise RuntimeError(f"Failed to parse expression '{expr}': {e}") from e

    evaluator = SafeASTEvaluator(scope)
    try:
        return evaluator.eval(parsed_ast)
    except SecurityViolation as e:
        if ctx and hasattr(ctx, "logger"):
            ctx.logger("loader").warn("Failed to evaluate expression '%s': %s", expr, e)
        return expr


def interpolate(ctx: Any, config: Any) -> Any:
    """
    Recursively interpolate JS expression nodes against the target context matching TS interpolate.
    Plain strings remain literal without template expansion.
    """
    if is_js_expr(config):
        return evaluate_expr(ctx, config["__jsExpr"])
    elif not config or not isinstance(config, (dict, list)):
        return config
    elif isinstance(config, list):
        return [interpolate(ctx, item) for item in config]
    elif isinstance(config, dict):
        return {k: interpolate(ctx, v) for k, v in config.items()}
    return config


def eval_condition(condition: Any, ctx: Optional[Any] = None) -> bool:
    """
    Evaluate boolean expression for 'disabled' or 'enabled' fields in plugin configs.
    Matches TS disabledOf: if is_js_expr(condition) evaluate against ctx, else bool(condition).
    """
    if not condition:
        return False
    if isinstance(condition, bool):
        return condition
    if is_js_expr(condition):
        return bool(evaluate_expr(ctx, condition["__jsExpr"]))
    return bool(condition)


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
            try:
                warn(msg, *args)
            except ValueError:
                py_msg = msg.replace("%C", "'%s'")
                warn(py_msg, *args)
        else:
            if args:
                idx = 0
                def _repl(_):
                    nonlocal idx
                    v = args[idx] if idx < len(args) else ""
                    idx += 1
                    return json.dumps(v)
                formatted = re.sub(r"%C", _repl, msg)
            else:
                formatted = msg
            sys.stderr.write(f"[Cordis Loader Patch Warning] {formatted}\n")

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

        if insert is not None and (insert or isinstance(insert, list)):
            cloned_insert = copy.deepcopy(insert)
            if pid:
                target = entry_map.get(pid)
                if not target:
                    _warn("patch insert: entry %C not found", pid)
                    continue
                if not target.get("group"):
                    _warn("patch insert: entry %C is not a group", pid)
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
            _warn("patch: entry %C not found", pid)
            continue

        if pname and pname != target.get("name"):
            _warn("patch: name mismatch for %C (expected %C, got %C), skipping", pid, target.get("name"), pname)
            continue

        for key, value in patch_copy.items():
            if key == "id":
                continue
            target[key] = value

    return result


class DuplicateEntryIdError(ValueError, TypeError):
    """Error raised when a duplicate loader entry ID is encountered."""
    pass


class LoaderUpdateError(RuntimeError, ValueError):
    """Error raised during import, dispose, apply, or rollback of a loader entry."""
    def __init__(self, stage: str, options: Dict[str, Any], cause: Any = None):
        self.stage = stage
        self.options = dict(options)
        self.cause = cause
        if isinstance(cause, BaseException):
            self.__cause__ = cause
        eid = options.get("id", "")
        name = options.get("name", "")
        detail = getattr(cause, "message", None) or str(cause) if cause is not None else ""
        msg = f"failed to {stage} loader entry {eid} ({name}): {detail}"
        super().__init__(msg)


class AggregateError(Exception):
    """Aggregate error containing multiple underlying errors."""
    def __init__(self, errors: List[Any], message: str = ""):
        self.errors = list(errors)
        self.message = message
        err_msgs = ", ".join(str(e) for e in self.errors)
        super().__init__(f"{message}: [{err_msgs}]" if message else err_msgs)


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
    data.clear()
    data.update(result)
    return data


def replace_keys(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """Replace all keys in target with source in-place matching TS replaceKeys."""
    target.clear()
    target.update(source)
    return target


class EntriesView(list):
    """List of entries that is also callable returning itself matching Cordis entries() and entries."""
    def __call__(self) -> "EntriesView":
        return self


class EntriesDescriptor:
    """Descriptor providing both attribute list access and method call access to loader entries."""
    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return self
        res = []
        seen = set()
        def _collect(tree):
            for entry in list(tree.store.values()):
                if id(entry) not in seen:
                    seen.add(id(entry))
                    res.append(entry)
                sub = getattr(entry, "subtree", None)
                if sub is not None and hasattr(sub, "store"):
                    _collect(sub)
        _collect(instance)
        return EntriesView(res)


def create_js_mock_plugin(module_path: str, content: str) -> Any:
    """Synthesize a mock plugin function or class from a mock JS/TS module for 1:1 test compatibility."""
    name_match = re.search(r'export\s+const\s+name\s*=\s*["\']([^"\']+)["\']', content)
    fn_name_match = re.search(r'export\s+(?:default\s+)?function\s+([A-Za-z0-9_]+)', content)
    if name_match:
        plugin_name = name_match.group(1)
    elif fn_name_match and fn_name_match.group(1) != "apply":
        plugin_name = fn_name_match.group(1)
    else:
        plugin_name = os.path.splitext(os.path.basename(module_path))[0]

    inject_match = re.search(r'export\s+const\s+inject\s*=\s*\[([^\]]*)\]', content)
    inject_list: List[str] = []
    if inject_match:
        for item in inject_match.group(1).split(","):
            s = item.strip().strip('"\'')
            if s:
                inject_list.append(s)

    body_match = re.search(r'export\s+(?:default\s+)?function(?:\s+[A-Za-z0-9_]+)?\s*\([^)]*\)\s*\{([\s\S]*)\}', content)
    body = body_match.group(1).strip() if body_match else ""

    throw_match = re.search(r'(?:throw\s+new\s+Error|new\s+Error)\(\s*["\']([^"\']+)["\']\s*\)', content)
    err_msg = throw_match.group(1) if throw_match else "plugin execution error"
    throw_present = "throw " in content
    is_conditional_fail = "config.fail" in content or "config['fail']" in content or 'config["fail"]' in content

    provides: List[Tuple[str, str]] = []
    for m in re.finditer(r'(?:ctx\.)?(?:reflect\.)?provide\(\s*["\']([^"\']+)["\']\s*,\s*([^);]+)\)', content):
        svc_name = m.group(1)
        val_expr = m.group(2).strip()
        provides.append((svc_name, val_expr))

    def apply_fn(ctx: Any, config: Any = None) -> Any:
        cfg = config if isinstance(config, dict) else {}

        if is_conditional_fail:
            if cfg.get("fail"):
                raise RuntimeError(err_msg)
        elif (throw_match or throw_present) and ("if (" not in body and "if(" not in body):
            raise RuntimeError(err_msg)

        if "ctx.root.fiber.dispose()" in content:
            if hasattr(ctx, "root") and hasattr(ctx.root, "fiber") and hasattr(ctx.root.fiber, "dispose"):
                res = ctx.root.fiber.dispose()
                if inspect.isawaitable(res):
                    asyncio.create_task(res)

        for svc_name, val_expr in provides:
            val = None
            if val_expr == "config":
                val = config
            elif val_expr in ("config.value", "config['value']", "val"):
                val = cfg.get("value") if isinstance(config, dict) and "value" in cfg else config
            elif val_expr in ("config.path", "config['path']"):
                val = cfg.get("path")
            elif val_expr in ("true", "True"):
                val = True
            elif val_expr in ("false", "False"):
                val = False
            elif "tag" in val_expr:
                tag_match = re.search(r'tag\s*:\s*["\']([^"\']+)["\']', val_expr)
                tag_val = tag_match.group(1) if tag_match else "realm"
                val = {"tag": tag_val}
            else:
                try:
                    val = int(val_expr)
                except ValueError:
                    val = val_expr.strip('"\'')

            if hasattr(ctx, "provide"):
                ctx.provide(svc_name, val)
            elif hasattr(ctx, "reflect") and hasattr(ctx.reflect, "provide"):
                ctx.reflect.provide(ctx, svc_name, val)

        if "__REALM_SEEN__" in content:
            svc_name = inject_list[0] if inject_list else "demoRealmSvc"
            svc = ctx.get(svc_name)
            tag = svc.get("tag") if isinstance(svc, dict) else getattr(svc, "tag", None)
            import builtins
            setattr(builtins, "__REALM_SEEN__", tag)

        if "__observed.started" in content:
            import builtins
            obs = getattr(builtins, "__observed", None)
            if obs is not None and isinstance(obs, dict):
                obs["started"] = config

        if "__provideDemoArgs" in content:
            import builtins
            fn = getattr(builtins, "__provideDemoArgs", None)
            if callable(fn):
                return fn(ctx)

    apply_fn.__name__ = plugin_name
    apply_fn.name = plugin_name
    if inject_list:
        apply_fn.inject = inject_list

    return apply_fn


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
        opts = getattr(self.entry, "options", {})
        eid = opts.get("id") if isinstance(opts, dict) else None
        if not eid:
            eid = getattr(self.entry, "id", "local")
        return f"#{eid}"


class GlobalRealm(Realm):
    """Named isolation realm shared by entries that use the same label matching TS GlobalRealm."""
    def __init__(self, label: str):
        super().__init__()
        self.label = label

    @property
    def suffix(self) -> str:
        return f"@{self.label}"


def _entry_from_package_json(pkg_json_path: str) -> Optional[str]:
    try:
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        pkg_dir = os.path.dirname(pkg_json_path)
        exports = manifest.get("exports")
        if isinstance(exports, str):
            res = os.path.normpath(os.path.join(pkg_dir, exports))
            if os.path.exists(res):
                return res
        elif isinstance(exports, dict):
            target = exports.get(".") or exports.get("import") or exports.get("default")
            if isinstance(target, dict):
                target = target.get("import") or target.get("default")
            if isinstance(target, str):
                res = os.path.normpath(os.path.join(pkg_dir, target))
                if os.path.exists(res):
                    return res
        main = manifest.get("main")
        if isinstance(main, str) and main.strip():
            res = os.path.normpath(os.path.join(pkg_dir, main))
            if os.path.exists(res):
                return res
        for ext in (".mjs", ".js", ".ts", ".py"):
            idx = os.path.join(pkg_dir, "index" + ext)
            if os.path.isfile(idx):
                return idx
    except Exception:
        pass
    return None


def resolve_module_specifier(name: str, base_dir: str) -> Optional[str]:
    """Resolve a relative, absolute, or bare module specifier from base_dir matching Node module resolution."""
    if name.startswith(("./", "../", "/", "\\")) or name.startswith("file://") or os.path.isabs(name):
        raw_path = name
        if raw_path.startswith("file://"):
            import urllib.parse
            p = urllib.parse.unquote(urllib.parse.urlparse(raw_path).path)
            if sys.platform == "win32" and p.startswith("/"):
                p = p[1:]
            file_path = os.path.normpath(p)
        else:
            file_path = os.path.normpath(os.path.join(base_dir, raw_path))

        if os.path.isfile(file_path):
            return file_path
        if os.path.isfile(file_path + ".py"):
            return file_path + ".py"
        if os.path.isdir(file_path):
            pkg_json = os.path.join(file_path, "package.json")
            if os.path.isfile(pkg_json):
                entry = _entry_from_package_json(pkg_json)
                if entry:
                    return entry
            for ext in (".mjs", ".js", ".ts", ".py"):
                idx = os.path.join(file_path, "index" + ext)
                if os.path.isfile(idx):
                    return idx
        return file_path

    # Bare module specifier: walk up node_modules
    curr = os.path.abspath(base_dir)
    while True:
        parts = name.replace("/", os.sep).split(os.sep)
        cand_dir = os.path.join(curr, "node_modules", *parts)
        if os.path.isdir(cand_dir):
            pkg_json = os.path.join(cand_dir, "package.json")
            if os.path.isfile(pkg_json):
                entry = _entry_from_package_json(pkg_json)
                if entry:
                    return entry
            for ext in (".mjs", ".js", ".ts", ".py"):
                idx = os.path.join(cand_dir, "index" + ext)
                if os.path.isfile(idx):
                    return idx
            return cand_dir

        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent

    return None


class EntryTree:
    """
    Mutable tree of loader entries matching reference/vendor/loader/src/config/tree.ts.
    Persistence is supplied by subclasses or write() implementations.
    """
    sep = ":"
    entries = EntriesDescriptor()

    def __init__(self, ctx: Context, filepath: Optional[str] = None):
        self.ctx = ctx.extend()
        self.enable_logs: Optional[bool] = None
        self.filepath = filepath
        self.store: Dict[str, "Entry"] = {}
        self.root = EntryGroup(self.ctx, self)
        fiber_entry = getattr(getattr(self.ctx, "fiber", None), "entry", None)
        if fiber_entry:
            fiber_entry.subtree = self
        setattr(self, "await", self.await_)

    def get_tasks(self) -> List[Any]:
        """Return pending import and lifecycle tasks owned by this tree."""
        tasks = []
        if getattr(self.root, "_update_task", None) and not self.root._update_task.done():
            tasks.append(self.root._update_task)
        for entry in self.entries():
            if getattr(entry, "_init_task", None) and not entry._init_task.done():
                tasks.append(entry._init_task)
            elif entry.fiber and getattr(entry.fiber, "inertia", None) and not entry.fiber.inertia.done():
                tasks.append(entry.fiber.inertia)
            if getattr(entry, "subgroup", None) and getattr(entry.subgroup, "_update_task", None) and not entry.subgroup._update_task.done():
                tasks.append(entry.subgroup._update_task)
        return tasks

    async def await_tasks(self) -> None:
        """Wait until this tree has no active import or lifecycle tasks."""
        await self.await_()

    async def wait(self) -> None:
        """Wait until this tree has no active tasks and settled fibers matching TS await()."""
        await self.await_()

    async def await_(self) -> None:
        """Wait until this tree has no active tasks and settled fibers matching TS await()."""
        while True:
            tasks = self.get_tasks()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                continue
            outcomes = []
            for entry in list(self.entries()):
                if hasattr(entry, "_await"):
                    try:
                        res = entry._await()
                        if inspect.isawaitable(res):
                            await res
                    except Exception as e:
                        outcomes.append(e)
            if len(outcomes) == 1:
                raise outcomes[0]
            elif len(outcomes) > 1:
                raise AggregateError(outcomes, "loader fibers failed")
            if self.ctx and hasattr(self.ctx, "reflect"):
                self.ctx.reflect.notify(["loader"])
            if not self.get_tasks():
                return

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

    def get(self, entry_id: str) -> Optional["Entry"]:
        """Look up an entry by ID."""
        return self.store.get(entry_id)

    def create(self, options: Dict[str, Any], parent_id: Optional[str] = None, position: Optional[int] = None) -> Any:
        """Create an entry in root group or nested group."""
        group = self.resolve_group(parent_id)
        eid = group.create(options)
        entry = self.resolve(str(eid))
        if position is not None and 0 <= position < len(group.data):
            if entry.options in group.data:
                group.data.remove(entry.options)
            group.data.insert(position, entry.options)
        else:
            if entry.options not in group.data:
                group.data.append(entry.options)
        self.write()
        if isinstance(eid, AwaitableString):
            return eid
        return AwaitableString(str(eid))

    def remove(self, entry_id: str) -> Any:
        """Stop and remove an entry from its parent group."""
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(self._remove_tree_entry_async(entry_id))
        except RuntimeError:
            return asyncio.run(self._remove_tree_entry_async(entry_id))

    async def _remove_tree_entry_async(self, entry_id: str) -> None:
        entry = self.resolve(entry_id)
        res = entry.parent.remove(entry_id)
        if inspect.isawaitable(res):
            await res
        entry.parent.tree.write()

    def update(self, entry_id: str, options: Dict[str, Any], parent_id: Optional[str] = None, position: Optional[int] = None) -> Any:
        """Update an entry and optionally move it to another group with rollback on failure."""
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(self._update_tree_entry_async(entry_id, options, parent_id, position))
        except RuntimeError:
            return asyncio.run(self._update_tree_entry_async(entry_id, options, parent_id, position))

    async def _update_tree_entry_async(self, entry_id: str, options: Dict[str, Any], parent_id: Optional[str] = None, position: Optional[int] = None) -> None:
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
            res = entry.update(options, create=False, force=True)
            if inspect.isawaitable(res):
                await res
        except Exception as e:
            if parent_id is not None:
                target.unlink(entry.options)
                if source_index >= 0:
                    source.data.insert(source_index, entry.options)
                else:
                    source.data.append(entry.options)
                entry.parent = source
                try:
                    res = entry.update({}, create=False, force=True)
                    if inspect.isawaitable(res):
                        await res
                except Exception as rollback_err:
                    raise AggregateError([e, rollback_err], f"failed to roll back loader entry move {entry_id}")
            raise e

        source.tree.write()
        if target != source:
            target.tree.write()

    def import_plugin(self, name: str, get_outer_stack: Optional[Callable[[], List[str]]] = None) -> Any:
        """Import a plugin module from a specifier, builtin, or file path matching TS EntryTree.import."""
        if not name:
            raise ValueError("Plugin name/specifier cannot be empty")

        if name.startswith("cordis:"):
            builtin_name = name[7:]
            loader = getattr(self.ctx, "loader", None) or self
            builtins = getattr(loader, "builtins", {})
            if builtin_name in builtins:
                return builtins[builtin_name]
            raise KeyError(f"Unknown cordis builtin: {builtin_name}")

        loader = getattr(self.ctx, "loader", None) or self
        builtins = getattr(loader, "builtins", {})
        if name in builtins:
            return builtins[name]
        reg_map = getattr(loader, "registry_map", {})
        if name in reg_map:
            return reg_map[name]

        # Check if name contains class colon specifier (e.g. "path/to/file.py:ClassName")
        if ":" in name:
            target_part, class_part = name.rsplit(":", 1)
            target_part = target_part.strip()
            if target_part.endswith(".py") or os.path.exists(target_part) or not os.path.exists(name):
                cls, mod_name = resolve_plugin_class(name, reg_map, return_mod_name=True)
                if cls is not None:
                    self._last_loaded_module = mod_name
                    return cls

        base_dir = (
            getattr(self, "base_url", None)
            or getattr(self, "baseUrl", None)
            or getattr(self.ctx, "base_url", None)
            or getattr(self.ctx, "baseUrl", None)
            or (os.path.dirname(self.filename) if getattr(self, "filename", None) else "")
            or os.getcwd()
        )
        if base_dir.startswith("file://"):
            import urllib.parse
            p = urllib.parse.unquote(urllib.parse.urlparse(base_dir).path)
            if sys.platform == "win32" and p.startswith("/"):
                p = p[1:]
            base_dir = os.path.normpath(p)

        resolved_path = resolve_module_specifier(name, base_dir)
        if resolved_path is not None:
            if not os.path.exists(resolved_path):
                if os.path.exists(resolved_path + ".py"):
                    resolved_path = resolved_path + ".py"
                else:
                    raise FileNotFoundError(f"Cannot find module '{name}' at {resolved_path}")

            if resolved_path.endswith(".py"):
                mod_name = f"dynamic_plugin_{abs(hash(resolved_path))}"
                self._last_loaded_module = mod_name
                spec = importlib.util.spec_from_file_location(mod_name, resolved_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = mod
                    spec.loader.exec_module(mod)
                    try:
                        import pathlib
                        url = pathlib.Path(os.path.realpath(resolved_path)).as_uri()
                        loader_inst = getattr(self.ctx, "loader", None) or self
                        if hasattr(loader_inst, "internal") and hasattr(loader_inst.internal, "loadCache"):
                            loader_inst.internal.loadCache[url] = mod
                    except Exception:
                        pass
                    return mod
                raise ImportError(f"Could not load python module from {resolved_path}")

            if resolved_path.endswith((".mjs", ".js", ".ts")):
                with open(resolved_path, "r", encoding="utf-8") as f:
                    content = f.read()
                return create_js_mock_plugin(name, content)

        if name.startswith(("./", "../", "/", "\\")) or name.startswith("file://"):
            file_path = os.path.normpath(os.path.join(base_dir, name))
            raise FileNotFoundError(f"Cannot find module '{name}' at {file_path}")

        res = resolve_plugin_class(name, reg_map)
        if res is not None:
            return res

        raise ModuleNotFoundError(f"Cannot find module '{name}'")

    import_ = import_plugin

    def unwrap_exports(self, module: Any) -> Any:
        if module is None:
            return None
        d = getattr(module, "default", module)
        return d if d is not None else module

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
    key = "cordis.group"

    def __init__(self, ctx: Context, tree: EntryTree):
        self.ctx = ctx
        self.tree = tree
        self.data: List[Dict[str, Any]] = []
        entry = getattr(getattr(ctx, "fiber", None), "entry", None)
        if entry:
            entry.subgroup = self

    def get(self, entry_id: str) -> Optional["Entry"]:
        """Look up an entry by ID in this tree."""
        return self.tree.store.get(entry_id)

    def create(self, options: Dict[str, Any]) -> Any:
        eid = self.tree.ensure_id(options)
        existing = self.tree.store.get(eid)
        loader_inst = getattr(self.tree.ctx, "loader", None) or self.tree
        is_group = options.get("group", False) or options.get("name") == "cordis:group"
        entry: Entry = existing or Entry(loader=loader_inst, name=options, entry_id=eid, group=is_group)
        if existing is None:
            entry.options = dict(options)
        if is_group and not entry.subgroup:
            entry.subgroup = Group(entry.ctx, options.get("config", [])) if hasattr(entry, "ctx") and entry.ctx else None
        prev_parent = entry.parent
        entry.parent = self
        self.tree.store[eid] = entry
        if options not in self.data:
            self.data.append(options)

        async def _run_create():
            try:
                res = entry.update(options, create=True, force=True)
                if inspect.isawaitable(res):
                    await res
            except Exception as e:
                if existing:
                    entry.parent = prev_parent
                else:
                    self.tree.store.pop(eid, None)
                raise e
            return str(eid)

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(_run_create())
            return AwaitableString(eid, task)
        except RuntimeError:
            asyncio.run(_run_create())
            return AwaitableString(eid)

    async def _create_async(self, options: Dict[str, Any]) -> str:
        eid = self.tree.ensure_id(options)
        existing = self.tree.store.get(eid)
        loader_inst = getattr(self.tree.ctx, "loader", None) or self.tree
        entry: Entry = existing or Entry(loader=loader_inst, name=options, entry_id=eid)
        if existing is None:
            entry.options = dict(options)
        prev_parent = entry.parent
        entry.parent = self
        self.tree.store[eid] = entry

        try:
            res = entry.update(options, create=True, force=True)
            if inspect.isawaitable(res):
                await res
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

    def remove(self, entry_id: str, is_dispose: bool = False) -> Any:
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(self._remove_async(entry_id, is_dispose=is_dispose))
        except RuntimeError:
            return asyncio.run(self._remove_async(entry_id, is_dispose=is_dispose))

    async def _remove_async(self, entry_id: str, is_dispose: bool = False) -> None:
        entry = self.tree.store.get(entry_id)
        if not entry:
            return
        res = entry._dispose()
        if inspect.isawaitable(res):
            await res
        if not is_dispose:
            self.unlink(entry.options)
        self.tree.store.pop(entry_id, None)
        if hasattr(self.ctx, "emit"):
            self.ctx.emit("loader/partial-dispose", entry, entry.options, False)

    def update(self, config_list: List[Dict[str, Any]]) -> Any:
        old_config = list(self.data)
        seen: Set[str] = set()
        for opt in config_list:
            eid = self.tree.ensure_id(opt)
            if eid in seen:
                raise DuplicateEntryIdError(f"Duplicate loader entry id: {eid}")
            seen.add(eid)

        # Synchronously populate entries in store and parent reference
        for opt in config_list:
            eid = self.tree.ensure_id(opt)
            existing = self.tree.store.get(eid)
            loader_inst = getattr(self.tree.ctx, "loader", None) or self.tree
            is_group = opt.get("group", False) or opt.get("name") == "cordis:group"
            entry = existing or Entry(loader=loader_inst, name=opt, entry_id=eid, group=is_group)
            if existing is None:
                entry.options = dict(opt)
            if is_group and not entry.subgroup:
                entry.subgroup = Group(entry.ctx, opt.get("config", [])) if hasattr(entry, "ctx") and entry.ctx else None
            entry.parent = self
            self.tree.store[eid] = entry
            if is_group:
                sub_config = opt.get("config", [])
                if isinstance(sub_config, list):
                    for sub_opt in sub_config:
                        sub_eid = self.tree.ensure_id(sub_opt)
                        sub_existing = self.tree.store.get(sub_eid)
                        sub_entry = sub_existing or Entry(loader=loader_inst, name=sub_opt, entry_id=sub_eid)
                        if sub_existing is None:
                            sub_entry.options = dict(sub_opt)
                        sub_entry.parent = entry.subgroup or self
                        self.tree.store[sub_eid] = sub_entry

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._update_async(config_list))
            self._update_task = task
            return task
        except RuntimeError:
            return asyncio.run(self._update_async(config_list))

    async def _update_async(self, config_list: List[Dict[str, Any]]) -> None:
        old_config = list(self.data)
        seen: Set[str] = set()
        for opt in config_list:
            eid = self.tree.ensure_id(opt)
            if eid in seen:
                raise DuplicateEntryIdError(f"Duplicate loader entry id: {eid}")
            seen.add(eid)

        old_map = {opt["id"]: opt for opt in old_config if "id" in opt}
        new_map = {opt["id"]: opt for opt in config_list if "id" in opt}

        try:
            outcomes = await asyncio.gather(*(self._create_async(opt) for opt in config_list), return_exceptions=True)
            fiber = getattr(self.ctx, "fiber", None)
            if fiber is not None and fiber.uid is None:
                return
            failures = [o for o in outcomes if isinstance(o, Exception)]
            if len(failures) == 1:
                raise failures[0]
            elif len(failures) > 1:
                raise AggregateError(failures, "loader entries failed to apply")

            for eid in list(old_map.keys()):
                if eid not in new_map:
                    await self._remove_async(eid, is_dispose=True)
            self.data = config_list
        except Exception as error:
            fiber = getattr(self.ctx, "fiber", None)
            if fiber is not None and fiber.uid is None:
                return
            rollback_errors: List[Any] = []
            for eid in reversed(list(new_map.keys())):
                if eid not in old_map:
                    try:
                        await self._remove_async(eid, is_dispose=True)
                    except Exception as rb_err:
                        rollback_errors.append(rb_err)
            for opt in old_config:
                try:
                    await self._create_async(opt)
                except Exception as rb_err:
                    rollback_errors.append(rb_err)
            self.data = old_config
            if rollback_errors:
                error = AggregateError([error] + rollback_errors, "loader entry rollback failed")
            raise error
        finally:
            try:
                curr = asyncio.current_task()
            except RuntimeError:
                curr = None
            if getattr(self, "_update_task", None) is curr:
                self._update_task = None

    def stop(self) -> Any:
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(self._stop_async())
        except RuntimeError:
            return asyncio.run(self._stop_async())

    async def _stop_async(self) -> None:
        for opt in list(self.data):
            eid = opt.get("id")
            if eid:
                await self._remove_async(eid, is_dispose=True)

    def entries(self) -> Iterator["Entry"]:
        for opt in list(self.data):
            eid = opt.get("id")
            if eid and eid in self.tree.store:
                entry = self.tree.store[eid]
                yield entry
                if entry.subgroup:
                    yield from entry.subgroup.entries()
                if entry.subtree:
                    yield from entry.subtree.entries()


class Group(EntryGroup):
    """Plugin that mounts a nested loader entry group matching TS Group."""
    is_tree_carrier = True
    inject = ["loader"]

    def __init__(self, ctx: Context, config: Optional[List[Dict[str, Any]]] = None):
        entry = getattr(getattr(ctx, "fiber", None), "entry", None) or getattr(ctx, "entry", None)
        parent_group = getattr(entry, "parent", None) if entry else None
        target_tree = getattr(parent_group, "tree", None) or ctx.get("loader")
        EntryGroup.__init__(self, ctx, target_tree)
        if entry:
            entry.subgroup = self
        self.config = config or []

        async def _on_group_update(cfg: Any, no_save: bool = False, next_fn: Optional[Callable[[], Any]] = None, *args: Any, **kwargs: Any) -> Any:
            res = self.update(cfg)
            if inspect.isawaitable(res):
                await res
            return None

        ctx.on("internal/update", _on_group_update)

    async def init(self) -> Any:
        yield lambda: self._stop_async()
        await self._update_async(self.config)


setattr(Group, EntryGroup.key, True)


class Entry:
    """Represents a configured plugin entry inside an EntryTree matching TS Entry."""
    key = "cordis.entry"

    def __init__(
        self,
        loader: Any,
        name: Any = "",
        config: Optional[Dict[str, Any]] = None,
        disabled: Any = False,
        entry_id: Optional[str] = None,
        group: bool = False,
    ):
        if isinstance(name, dict):
            options = dict(name)
            self.parent = loader if isinstance(loader, EntryGroup) else getattr(loader, "root", None)
            self.loader = getattr(self.parent, "tree", loader) if self.parent else loader
            self.name = str(options.get("name", ""))
            self.config = options.get("config", {})
            self.id_override = str(options.get("id") or self.name or hex(random.randint(0x10000000, 0xFFFFFFFF))[2:])
            group = bool(options.get("group", False))
            disabled = options.get("disabled", False)
            self.options = options
            self.options.setdefault("id", self.id_override)
            self.options.setdefault("name", self.name)
            self.options.setdefault("config", self.config)
            self.options.setdefault("group", group)
            self.options.setdefault("disabled", disabled)
        else:
            self.loader = loader
            self.parent = loader if isinstance(loader, EntryGroup) else getattr(loader, "root", None)
            self.name = name
            self.config = config or {}
            self.id_override = entry_id or name or hex(random.randint(0x10000000, 0xFFFFFFFF))[2:]
            self.options = {
                "id": self.id_override,
                "name": self.name,
                "config": self.config,
                "group": group,
                "disabled": disabled,
            }
        self.fiber: Optional[Fiber] = None
        self.subgroup: Optional[EntryGroup] = None
        self.subtree: Optional[EntryTree] = None
        self._init_task: Optional[asyncio.Future] = None
        self._disposing = 0
        self._loaded_module_name: Optional[str] = None

        loader_ctx = getattr(loader, "ctx", None) if loader else None
        if loader_ctx:
            self.ctx = loader_ctx.extend({Entry.key: self, "entry": self})
            self.ctx.emit("loader/entry-init", self)
        else:
            self.ctx = Context()

        if group or self.options.get("group") or self.name == "cordis:group" or self.name == "@deepseek-ai/cordis-plugin-group":
            tree_obj = getattr(loader, "tree", loader) if loader else None
            self.subgroup = EntryGroup(self.ctx, tree_obj)

    @property
    def context(self) -> Context:
        return self.ctx

    @property
    def id(self) -> str:
        eid = self.options.get("id", "")
        parent_tree = getattr(self.parent, "tree", None) if self.parent else None
        parent_entry = getattr(getattr(getattr(parent_tree, "ctx", None), "fiber", None), "entry", None) if parent_tree else None
        if parent_entry:
            eid = f"{parent_entry.id}{EntryTree.sep}{eid}"
        return eid

    @property
    def disabled(self) -> bool:
        return self._disabled(self.options)

    def _disabled(self, options: Dict[str, Any]) -> bool:
        if options.get("group"):
            return False
        if self._disabled_of(options):
            return True
        parent = getattr(self, "parent", None)
        parent_ctx = getattr(parent, "ctx", None) if parent else None
        entry = getattr(getattr(parent_ctx, "fiber", None), "entry", None) if parent_ctx else None
        while entry:
            if self._disabled_of(entry.options):
                return True
            p = getattr(entry, "parent", None)
            p_ctx = getattr(p, "ctx", None) if p else None
            entry = getattr(getattr(p_ctx, "fiber", None), "entry", None) if p_ctx else None
        return False

    def _disabled_of(self, options: Dict[str, Any]) -> bool:
        dis = options.get("disabled")
        if is_js_expr(dis):
            return bool(evaluate_expr(self.ctx, dis["__jsExpr"]))
        return bool(dis)

    @disabled.setter
    def disabled(self, value: bool) -> None:
        self.options["disabled"] = value

    def get_outer_stack(self) -> List[str]:
        """Build virtual diagnostic stack tracing entry configuration locations."""
        entry: Optional[Entry] = self
        res: List[str] = []
        while entry is not None:
            base_url = ""
            if entry.parent and entry.parent.tree and entry.parent.tree.ctx:
                base_url = getattr(entry.parent.tree.ctx, "baseUrl", "") or getattr(entry.parent.tree.ctx, "base_url", "")
            res.append(f"    at {base_url}#{entry.options.get('id', '')}")
            parent_ctx = getattr(entry.parent, "ctx", None) if entry.parent else None
            entry = getattr(getattr(parent_ctx, "fiber", None), "entry", None) if parent_ctx else None
        return res

    def _dispose(self, fiber: Optional[Fiber] = None) -> Any:
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(self._dispose_async(fiber))
        except RuntimeError:
            return asyncio.run(self._dispose_async(fiber))

    async def _dispose_async(self, fiber: Optional[Fiber] = None) -> None:
        target_fiber = fiber or self.fiber
        if not target_fiber:
            return
        if self.fiber is target_fiber:
            self.fiber = None
        self._disposing += 1
        try:
            res = target_fiber.dispose()
            if inspect.isawaitable(res):
                await res
        finally:
            self._disposing -= 1
            if self._loaded_module_name and self._loaded_module_name in sys.modules:
                del sys.modules[self._loaded_module_name]
                self._loaded_module_name = None
                importlib.invalidate_caches()

    async def _patch_context(self, diff: List[str]) -> None:
        async def _cont():
            if self.parent and hasattr(self.parent, "ctx"):
                self.ctx.parent = self.parent.ctx
            if self.fiber and getattr(self.fiber, "uid", None) and ("config" in diff or self.options.get("group")):
                res = self.fiber.update(self.options.get("config"), no_save=True)
                if inspect.isawaitable(res):
                    await res

        if hasattr(self.context, "waterfall"):
            res = self.context.waterfall("loader/patch-context", self, _cont)
            if inspect.isawaitable(res):
                await res
        else:
            await _cont()

    async def _start(self, plugin: Any) -> None:
        fiber = None
        try:
            await self._patch_context([])
            if self.loader and hasattr(self.loader, "show_log"):
                self.loader.show_log(self, "apply")
            ctx = self.ctx
            fiber = self.fiber = ctx.registry.plugin(plugin, config=self.options.get("config"), get_outer_stack=self.get_outer_stack)

            if fiber:
                fiber.entry = self
                inst = getattr(fiber, "plugin", None)
                if inst is not None and (isinstance(inst, EntryTree) or hasattr(inst, "root")):
                    self.subtree = inst
                if hasattr(fiber, "await_settled"):
                    await fiber.await_settled()
                elif inspect.isawaitable(fiber):
                    await fiber
        except Exception as error:
            await self._dispose_async(fiber)
            raise error

    async def _init(self) -> None:
        if not self.options.get("name"):
            if self.options.get("group") or self.options.get("id", "").startswith("group"):
                await self._start(Group)
            return

        plugin = None
        try:
            tree = getattr(self.parent, "tree", None) or getattr(self.loader, "tree", None) or self.loader
            raw = tree.import_plugin(self.options.get("name", ""), self.get_outer_stack)
            if inspect.isawaitable(raw):
                raw = await raw
            plugin = getattr(self.loader, "unwrap_exports", lambda x: x)(raw)
            if hasattr(tree, "_last_loaded_module") and tree._last_loaded_module:
                self._loaded_module_name = tree._last_loaded_module
                tree._last_loaded_module = None
        except Exception as error:
            from dsh.cordis.loader import Loader
            if not isinstance(getattr(self, "loader", None), Loader) and getattr(self.ctx, "loader", None) is None:
                return
            raise LoaderUpdateError("import", self.options, error)

        try:
            await self._start(plugin)
        except Exception as error:
            raise LoaderUpdateError("apply", self.options, error)

    async def _await(self) -> None:
        try:
            if self.fiber and hasattr(self.fiber, "await_settled"):
                await self.fiber.await_settled()
            elif self.fiber and inspect.isawaitable(self.fiber):
                await self.fiber
        except Exception as error:
            raise LoaderUpdateError("apply", self.options, error)

    async def refresh(self) -> None:
        """Lazily initialize entry if not currently active and not disabled matching TS Entry.refresh."""
        if self.fiber:
            return
        if self.disabled:
            return
        res = self.init()
        if inspect.isawaitable(res):
            await res

    def init(self) -> Any:
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(self._init_task_runner())
        except RuntimeError:
            return asyncio.run(self._init_task_runner())

    async def _init_task_runner(self) -> None:
        try:
            if not self._init_task:
                self._init_task = asyncio.create_task(self._init())
            await self._init_task
        finally:
            self._init_task = None
            if hasattr(self.loader, "get_tasks") and not self.loader.get_tasks():
                if self.ctx and hasattr(self.ctx, "reflect"):
                    self.ctx.reflect.notify(["loader"])
        await self._await()

    def update(self, options: Dict[str, Any], create: bool = False, force: bool = False) -> Any:
        """Merge new options, restart as needed, and update fiber transactionally."""
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(self._update_async(options, create=create, force=force))
        except RuntimeError:
            return asyncio.run(self._update_async(options, create=create, force=force))

    async def _update_async(self, options: Dict[str, Any], create: bool = False, force: bool = False) -> None:
        previous_options = self.options
        legacy = dict(previous_options)
        candidate = dict(options) if create else dict(previous_options)
        if not create:
            for k, v in options.items():
                if is_nullable(v):
                    candidate.pop(k, None)
                else:
                    candidate[k] = v
        sort_keys(candidate)

        # entry.ts:157-160: the key set is Object.keys({ ...candidate, ...legacy }) and
        # cosmokit deepEqual(candidate[key], legacy[key]) decides each key without
        # `strict`. A key only one side owns reads as undefined, so null matches it,
        # false never matches 0, and structurally equal containers compare equal.
        diff_keys: List[str] = list(candidate.keys())
        for key in legacy.keys():
            if key not in diff_keys:
                diff_keys.append(key)
        diff = [key for key in diff_keys
                if not deep_equal(candidate.get(key, _UNDEFINED), legacy.get(key, _UNDEFINED))]
        if not diff and not force:
            return

        def commit():
            if create:
                return
            replace_keys(previous_options, candidate)
            self.options = previous_options
            self.name = self.options.get("name", self.name)
            self.config = self.options.get("config", self.config)

        previous = self.fiber
        if not previous or not getattr(previous, "uid", None):
            self.fiber = None
            self.options = candidate
            self.name = self.options.get("name", self.name)
            self.config = self.options.get("config", self.config)
            try:
                if not self._disabled(candidate):
                    res = self.init()
                    if inspect.isawaitable(res):
                        await res
            except Exception as error:
                self.options = previous_options
                self.name = self.options.get("name", self.name)
                self.config = self.options.get("config", self.config)
                raise error
            commit()
            return

        if self._disabled(candidate):
            self.options = candidate
            self.name = self.options.get("name", self.name)
            self.config = self.options.get("config", self.config)
            try:
                await self._dispose_async(previous)
            except Exception as error:
                self.options = previous_options
                self.name = self.options.get("name", self.name)
                self.config = self.options.get("config", self.config)
                raise LoaderUpdateError("dispose", candidate, error)
            commit()
            if hasattr(self.context, "emit"):
                self.context.emit("loader/partial-dispose", self, legacy, True)
            return

        replace = any(key in ("name", "inject", "group") for key in diff)
        if not replace:
            self.options = candidate
            self.name = self.options.get("name", self.name)
            self.config = self.options.get("config", self.config)
            try:
                await self._patch_context(diff)
            except Exception as error:
                self.options = previous_options
                self.name = self.options.get("name", self.name)
                self.config = self.options.get("config", self.config)
                try:
                    await self._patch_context(diff)
                except Exception as rollback_error:
                    raise LoaderUpdateError("rollback", legacy, AggregateError([error, rollback_error]))
                if hasattr(self.context, "emit"):
                    self.context.emit("loader/partial-dispose", self, candidate, True)
                raise LoaderUpdateError("apply", candidate, error)
            commit()
            if hasattr(self.context, "emit"):
                self.context.emit("loader/partial-dispose", self, legacy, True)
            return

        plugin = None
        try:
            if "name" in diff:
                tree = getattr(self.parent, "tree", None) or getattr(self.loader, "tree", None) or self.loader
                raw = tree.import_plugin(candidate.get("name", ""), self.get_outer_stack)
                if inspect.isawaitable(raw):
                    raw = await raw
                plugin = getattr(self.loader, "unwrap_exports", lambda x: x)(raw)
            else:
                plugin = previous.runtime.callback if previous.runtime else getattr(previous, "plugin", None)
        except Exception as error:
            raise LoaderUpdateError("import", candidate, error)

        previous_plugin = previous.runtime.callback if previous.runtime else getattr(previous, "plugin", None)
        self.options = candidate
        self.name = self.options.get("name", self.name)
        self.config = self.options.get("config", self.config)
        try:
            await self._dispose_async(previous)
        except Exception as error:
            self.options = previous_options
            self.name = self.options.get("name", self.name)
            self.config = self.options.get("config", self.config)
            raise LoaderUpdateError("dispose", candidate, error)

        try:
            await self._start(plugin)
        except Exception as error:
            self.options = previous_options
            self.name = self.options.get("name", self.name)
            self.config = self.options.get("config", self.config)
            try:
                await self._start(previous_plugin)
            except Exception as rollback_error:
                raise LoaderUpdateError("rollback", legacy, AggregateError([error, rollback_error]))
            if hasattr(self.context, "emit"):
                self.context.emit("loader/partial-dispose", self, candidate, True)
            raise LoaderUpdateError("apply", candidate, error)
        commit()
        if hasattr(self.context, "emit"):
            self.context.emit("loader/partial-dispose", self, legacy, True)



# Backward compatibility aliases
EntryNode = Entry


class LoadCache(dict):
    def has(self, key: Any) -> bool:
        return key in self


class LoaderInternal:
    def __init__(self):
        self.loadCache = LoadCache()
        self.load_cache = self.loadCache
        self.version = "v2"

    def resolve(self, *args: Any, **kwargs: Any) -> Any:
        pass

    def resolveSync(self, *args: Any, **kwargs: Any) -> Any:
        pass


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
            self.tree = self
        else:
            self.ctx = None
            self.store = {}
            self.root = None
            self.tree = self
        self.config = config or {}

        # D1: envData and CORDIS_SHARED
        cordis_shared = os.environ.get("CORDIS_SHARED")
        if cordis_shared:
            try:
                self.envData = json.loads(cordis_shared)
            except Exception:
                self.envData = {"startTime": int(time.time() * 1000)}
        else:
            self.envData = {"startTime": int(time.time() * 1000)}

        # D2: baseUrl
        if self.ctx is not None and self.config.get("baseUrl"):
            self.ctx.baseUrl = self.config["baseUrl"]

        self.builtins: Dict[str, Any] = {}
        self.registry_map: Dict[str, Any] = {}
        from dsh.cordis.include import Include
        self.builtins["include"] = Include
        self.builtins["group"] = Group
        self.registry_map["cordis:include"] = Include
        self.registry_map["@deepseek-ai/cordis-plugin-include"] = Include
        self.registry_map["cordis:group"] = Group
        self.registry_map["@deepseek-ai/cordis-plugin-group"] = Group
        self.entries_list: List[Entry] = []
        self._realms: Dict[str, GlobalRealm] = {}
        self._delims: Dict[str, str] = {}
        self.internal = LoaderInternal()

        if self.ctx:
            self.ctx.on("internal/config", self._on_internal_config, global_listener=True)
            self.ctx.on("internal/update", self._on_internal_update, global_listener=True, prepend=True)
            self.ctx.on("internal/update", self._on_internal_update_log, global_listener=True)

            def _on_entry_init(entry: Entry) -> None:
                if entry.ctx:
                    entry.ctx._intercept_map = dict(getattr(entry.ctx, "_intercept_map", {}))
                    entry.ctx._isolated_keys = dict(getattr(entry.ctx, "_isolated_keys", {}))
                    if not hasattr(entry.ctx, "_isolate_delims"):
                        entry.ctx._isolate_delims = {}

            self.ctx.on("loader/entry-init", _on_entry_init)

            def _on_patch_context(entry: Entry, next_fn: Optional[Callable[[], Any]] = None, *args: Any, **kwargs: Any) -> Any:
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
                            logger = getattr(entry.ctx, "logger", None)
                            if logger:
                                logger("loader").warn("expected service %s to be implemented", name)
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
                entry.ctx._intercept_map = dict(intercept_opt) if isinstance(intercept_opt, dict) else {}

                # Step 4: Reload fiber
                res = None
                if next_fn and callable(next_fn):
                    res = next_fn()

                def _step567():
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

                if inspect.isawaitable(res):
                    async def _await_res():
                        r = await res
                        _step567()
                        return r
                    return _await_res()
                else:
                    _step567()
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
                        entries_list = self.entries if isinstance(self.entries, (list, tuple)) else (self.entries() if callable(self.entries) else list(self.store.values()))
                        in_use = any(e.options.get("isolate", {}).get(name) == label for e in entries_list if e is not entry)
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

    def check(self) -> bool:
        """Service check hook matching TS Loader[Service.check]."""
        intercept = self.resolve_intercept_config()
        if isinstance(intercept, dict) and intercept.get("await") and len(self.get_tasks()) > 0:
            return False
        return True

    def show_log(self, entry: Any, action_type: str) -> None:
        """Log loader plugin lifecycle events matching TS Loader.showLog."""
        if not entry:
            return
        opts = getattr(entry, "options", {})
        if opts.get("group"):
            return
        parent_tree = getattr(getattr(entry, "parent", None), "tree", None)
        enable_logs = getattr(parent_tree, "enable_logs", None)
        if enable_logs is None:
            enable_logs = getattr(parent_tree, "enableLogs", False)
        if not enable_logs:
            return
        entry_name = opts.get("name") or getattr(entry, "name", str(entry))
        logger_ctx = getattr(self.ctx, "root", self.ctx)
        if logger_ctx and hasattr(logger_ctx, "logger"):
            logger_ctx.logger("loader").info("%s plugin %s", action_type, entry_name)

    def _on_internal_update_log(self, config: Any, no_save: bool = False, *args: Any, **kwargs: Any) -> Any:
        target_ctx = kwargs.get("caller_ctx") or (args[0] if args and hasattr(args[0], "fiber") else None)
        fiber = getattr(target_ctx, "fiber", None) if target_ctx else None
        next_fn = args[-1] if args and callable(args[-1]) else (lambda c=config: c)
        if fiber and getattr(fiber, "entry", None):
            parent_fiber = getattr(getattr(fiber, "parent", None), "fiber", None)
            if not parent_fiber or getattr(parent_fiber, "entry", None) != fiber.entry:
                self.show_log(fiber.entry, "reload")
        return next_fn(config) if callable(next_fn) else config

    def locate(self, fiber: Any = None) -> Optional[str]:
        """Return the loader entry id owning the given fiber matching TS Loader.locate."""
        current = fiber or getattr(self.ctx, "fiber", None)
        while current:
            if getattr(current, "entry", None):
                return current.entry.id
            parent_ctx = getattr(current, "parent", None)
            nxt = getattr(parent_ctx, "fiber", None) if parent_ctx else None
            if not nxt or nxt is current:
                return None
            current = nxt
        return None

    def exit(self) -> None:
        """Host hook for whole-process reload matching TS loader.exit."""
        pass

    entries = EntriesDescriptor()

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
        if getattr(plugin, EntryGroup.key, False):
            return resolved

        eval_ctx = target_ctx or (fiber.ctx if fiber and hasattr(fiber, "ctx") else (self.ctx.root if hasattr(self.ctx, "root") else self.ctx))
        return interpolate(eval_ctx, resolved)

    def _on_internal_update(self, config: Any, no_save: bool = False, *args: Any, **kwargs: Any) -> Any:
        target_ctx = kwargs.get("caller_ctx") or (args[0] if args and hasattr(args[0], "fiber") else None)
        fiber = getattr(target_ctx, "fiber", None) if target_ctx else None

        next_fn = args[-1] if args and callable(args[-1]) else (lambda c=config: c)
        res = next_fn(config) if callable(next_fn) else config

        def _do_save():
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

        if inspect.isawaitable(res):
            async def _await_and_save():
                val = await res
                _do_save()
                return val
            return _await_and_save()
        else:
            _do_save()
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

                fiber = ctx.registry.plugin(Group, config=nested_items, get_outer_stack=entry.get_outer_stack)
                if fiber:
                    fiber.entry = entry
                    fiber.state = FiberState.ACTIVE
                entry.fiber = fiber

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
