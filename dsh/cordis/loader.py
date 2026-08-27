"""Transactional Cordis loader with Python module import mapping."""

import ast
import importlib
import importlib.util
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import yaml

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader_entry import Entry, EntryNode
from dsh.cordis.loader_group import EntryGroup, Group, LoaderAggregateError
from dsh.cordis.loader_isolate import GlobalRealm, IsolateManager, LocalRealm, Realm, install_isolate
from dsh.cordis.loader_tree import EntryTree
from dsh.cordis.registry import Inject
from dsh.cordis.service import Service
from dsh.cordis.utils import Tracker


class JsExpr(dict):
    def __init__(self, expression: str):
        super().__init__({"__jsExpr": expression})


def _js_constructor(loader: Any, node: Any) -> JsExpr:
    return JsExpr(loader.construct_scalar(node))


for _tag in ("tag:yaml.org,2002:js", "!js"):
    yaml.SafeLoader.add_constructor(_tag, _js_constructor)


def is_js_expr(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("__jsExpr"), str)


_EXPR_TOKEN = re.compile(
    r"\s*(?:(===|!==|\?\?|&&|\|\||>=|<=|[!?:(),<>])"
    r"|('(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
    r"|(-?(?:\d+\.\d+|\d+))"
    r"|([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*))"
)


def _tokenize_expression(source: str) -> List[Tuple[str, Any]]:
    tokens: List[Tuple[str, Any]] = []
    offset = 0
    while offset < len(source):
        match = _EXPR_TOKEN.match(source, offset)
        if match is None:
            if source[offset:].strip() == "":
                break
            raise ValueError("unexpected token at offset %d" % offset)
        operator, string, number, identifier = match.groups()
        if operator is not None:
            tokens.append(("operator", operator))
        elif string is not None:
            tokens.append(("literal", ast.literal_eval(string)))
        elif number is not None:
            value = float(number) if "." in number else int(number)
            tokens.append(("literal", value))
        else:
            tokens.append(("identifier", identifier))
        offset = match.end()
    tokens.append(("eof", None))
    return tokens


class _ExpressionParser:
    def __init__(self, source: str):
        self.tokens = _tokenize_expression(source)
        self.index = 0

    def _peek(self, value: Optional[str] = None) -> bool:
        token = self.tokens[self.index]
        return token[0] == "operator" and (value is None or token[1] == value)

    def _take(self, value: str) -> None:
        if not self._peek(value):
            raise ValueError("expected %s" % value)
        self.index += 1

    def parse(self) -> Any:
        node = self._conditional()
        if self.tokens[self.index][0] != "eof":
            raise ValueError("unexpected trailing expression")
        return node

    def _conditional(self) -> Any:
        node = self._nullish()
        if self._peek("?"):
            self.index += 1
            truthy = self._conditional()
            self._take(":")
            falsy = self._conditional()
            return ("conditional", node, truthy, falsy)
        return node

    def _nullish(self) -> Any:
        node = self._or()
        while self._peek("??"):
            self.index += 1
            node = ("binary", "??", node, self._or())
        return node

    def _or(self) -> Any:
        node = self._and()
        while self._peek("||"):
            self.index += 1
            node = ("binary", "||", node, self._and())
        return node

    def _and(self) -> Any:
        node = self._equality()
        while self._peek("&&"):
            self.index += 1
            node = ("binary", "&&", node, self._equality())
        return node

    def _equality(self) -> Any:
        node = self._unary()
        while self._peek() and self.tokens[self.index][1] in (
                "===", "!==", ">", "<", ">=", "<="):
            operator = self.tokens[self.index][1]
            self.index += 1
            node = ("binary", operator, node, self._unary())
        return node

    def _unary(self) -> Any:
        if self._peek("!"):
            self.index += 1
            return ("unary", "!", self._unary())
        return self._primary()

    def _primary(self) -> Any:
        token_type, value = self.tokens[self.index]
        if token_type == "operator" and value == "(":
            self.index += 1
            node = self._conditional()
            self._take(")")
            return node
        if token_type == "literal":
            self.index += 1
            return ("literal", value)
        if token_type != "identifier":
            raise ValueError("expected literal, identifier, or parenthesized expression")
        self.index += 1
        if self._peek("("):
            self.index += 1
            args = []
            if not self._peek(")"):
                while True:
                    args.append(self._conditional())
                    if not self._peek(","):
                        break
                    self.index += 1
            self._take(")")
            return ("call", value, args)
        return ("identifier", value)


def _context_member(value: Any, name: str) -> Any:
    if name.startswith("_"):
        raise ValueError("private context properties are not available")
    if isinstance(value, dict):
        if name not in value:
            raise KeyError(name)
        return value[name]
    return getattr(value, name)


def _context_chain_member(ctx: Any, name: str) -> Any:
    if name.startswith("_"):
        raise ValueError("private context properties are not available")
    current = ctx
    while current is not None:
        namespace = getattr(current, "__dict__", {})
        if name in namespace:
            return namespace[name]
        current = namespace.get("_parent")
    raise AttributeError(name)


def _resolve_identifier(ctx: Any, name: str) -> Any:
    if name == "true":
        return True
    if name == "false":
        return False
    if name in ("null", "undefined"):
        return None
    if name == "process.platform":
        return "win32" if os.name == "nt" else sys.platform
    if name == "process.version.length":
        return len(sys.version)
    if name.startswith("process.env."):
        return os.environ.get(name[len("process.env."):])
    if name == "baseUrl":
        return _context_chain_member(ctx, "baseUrl")
    if name.startswith("ctx."):
        value = ctx
        for part in name.split(".")[1:]:
            value = _context_member(value, part)
        return value
    raise ValueError("unsupported identifier %s" % name)


def _evaluate_node(ctx: Any, node: Any) -> Any:
    kind = node[0]
    if kind == "literal":
        return node[1]
    if kind == "identifier":
        return _resolve_identifier(ctx, node[1])
    if kind == "call":
        name = node[1]
        args = [_evaluate_node(ctx, arg) for arg in node[2]]
        if name == "process.cwd":
            if args:
                raise ValueError("process.cwd() takes no arguments")
            return os.getcwd()
        if name == "ctx.get":
            return ctx.get(*args)
        if name == "dshHomePath":
            callback = _context_chain_member(ctx, "dshHomePath")
            if not callable(callback):
                raise ValueError("dshHomePath is not callable")
            return callback(*args)
        raise ValueError("unsupported call %s" % name)
    if kind == "unary":
        return not bool(_evaluate_node(ctx, node[2]))
    if kind == "conditional":
        branch = node[2] if bool(_evaluate_node(ctx, node[1])) else node[3]
        return _evaluate_node(ctx, branch)
    if kind == "binary":
        operator = node[1]
        left = _evaluate_node(ctx, node[2])
        if operator == "??":
            return _evaluate_node(ctx, node[3]) if left is None else left
        if operator == "||":
            return left or _evaluate_node(ctx, node[3])
        if operator == "&&":
            return _evaluate_node(ctx, node[3]) if left else left
        right = _evaluate_node(ctx, node[3])
        if operator == "===":
            return type(left) is type(right) and left == right
        if operator == "!==":
            return not (type(left) is type(right) and left == right)
        if operator == ">":
            return left > right
        if operator == "<":
            return left < right
        if operator == ">=":
            return left >= right
        if operator == "<=":
            return left <= right
    raise ValueError("unsupported expression node")


def evaluate(ctx: Any, expression: str) -> Any:
    """Evaluate the safe JavaScript subset used by shipped loader configs."""
    try:
        return _evaluate_node(ctx, _ExpressionParser(expression).parse())
    except Exception as error:
        if isinstance(error, ValueError) and str(error).startswith(
                "unsupported loader !!js expression"):
            raise
        raise ValueError(
            "unsupported loader !!js expression %r: %s" % (expression, error)
        )


def interpolate(ctx: Any, value: Any) -> Any:
    if is_js_expr(value):
        return evaluate(ctx, value["__jsExpr"])
    if isinstance(value, list):
        return [interpolate(ctx, item) for item in value]
    if isinstance(value, dict):
        return {key: interpolate(ctx, item) for key, item in value.items()}
    return value


def eval_condition(condition: Any, ctx: Optional[Any] = None) -> bool:
    if is_js_expr(condition):
        return bool(evaluate(ctx or Context(), condition["__jsExpr"]))
    if isinstance(condition, str):
        source = condition[4:].strip() if condition.startswith("!!js") else condition
        return bool(evaluate(ctx or Context(), source))
    return bool(condition)


class Loader(EntryTree):
    name = "loader"

    def __init__(self, ctx: Optional[Context] = None,
                 config: Optional[Dict[str, Any]] = None):
        owner = ctx or Context()
        self.config = config or {}
        base_url = self.config.get("baseUrl") or getattr(owner, "baseUrl", None) or os.getcwd()
        tree_ctx = owner.extend({"baseUrl": base_url})
        self.owner_ctx = owner
        self.registry_map: Dict[str, Any] = {}
        self.builtins: Dict[str, Any] = {"group": Group}
        shared = os.environ.get("CORDIS_SHARED")
        self.env_data = json.loads(shared) if shared else {"startTime": int(time.time() * 1000)}
        self.envData = self.env_data
        EntryTree.__init__(self, tree_ctx)
        self._cordis_tracker = Tracker(
            associate="loader", property_name="ctx", no_shadow=True
        )
        owner.provide("loader", self, check=Loader._check_availability)
        self.isolation: IsolateManager = install_isolate(owner)
        owner.on("internal/config", self._on_internal_config, global_listener=True)
        owner.on("internal/update", self._on_internal_update, prepend=True, global_listener=True)
        owner.on("internal/plugin", self._on_internal_plugin, global_listener=True)

    @staticmethod
    def is_js_expr(value: Any) -> bool:
        return is_js_expr(value)

    @staticmethod
    def evaluate(ctx: Any, expression: str) -> Any:
        return evaluate(ctx, expression)

    @staticmethod
    def interpolate(ctx: Any, value: Any) -> Any:
        return interpolate(ctx, value)

    def _on_internal_config(self, config: Any, next_fn: Any) -> Any:
        return next_fn()

    def _on_internal_update(self, config: Any, no_save: bool, next_fn: Any) -> Any:
        return next_fn()

    def _on_internal_plugin(self, fiber: Any) -> None:
        entry = getattr(fiber, "entry", None)
        if entry is None:
            current = getattr(fiber, "parent", None)
            while current is not None:
                entry = current.__dict__.get(Entry.key)
                if entry is not None:
                    fiber.entry = entry
                    Inject.resolve(entry.options.get("inject"), fiber.inject)
                    break
                current = getattr(current, "_parent", None)
        if entry is None:
            return
        if getattr(fiber, "uid", None) is not None:
            return
        parent_fiber = getattr(getattr(fiber, "parent", None), "fiber", None)
        if getattr(parent_fiber, "entry", None) is entry:
            return
        runtime = getattr(fiber, "runtime", None)
        callback = getattr(runtime, "callback", None)
        if callback is None or not self.owner_ctx.registry.has(callback):
            return
        tree_owner = entry.parent.tree.ctx.fiber
        if getattr(tree_owner, "uid", None) is None or tree_owner.state == FiberState.UNLOADING:
            return
        if entry._disposing or entry.disabled:
            return
        entry.options["disabled"] = True
        entry.parent.tree.write()

    def _check_availability(self) -> bool:
        config = Service.resolve_intercept_config(self)
        return not (config.get("await") and self.get_tasks())

    def register_plugin_class(self, name_or_id: str, plugin: Any) -> None:
        self.registry_map[name_or_id] = plugin

    def import_plugin(self, name: str) -> Any:
        if not isinstance(name, str) or not name:
            raise ImportError("loader plugin name must be a non-empty string")
        if name.startswith("cordis:"):
            builtin = self.builtins.get(name[7:])
            if builtin is None:
                raise ImportError("unknown Cordis loader builtin: %s" % name)
            return builtin
        if name in self.registry_map:
            plugin = self.registry_map[name]
            if not callable(plugin) and not callable(getattr(plugin, "apply", None)):
                raise TypeError("registered loader plugin %r is not callable" % name)
            return plugin
        try:
            if name.startswith(".") or name.endswith(".py"):
                base = self.ctx.baseUrl
                base_dir = os.path.dirname(base) if os.path.isfile(base) else base
                path = os.path.abspath(os.path.join(base_dir, name))
                if not os.path.isfile(path):
                    raise ImportError("cannot import loader plugin %s from %s" % (name, path))
                module_name = "_dsh_loader_%s" % abs(hash(path))
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    raise ImportError("cannot create module spec for %s" % path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return self.unwrap_exports(module)
            return self.unwrap_exports(importlib.import_module(name))
        except ImportError as error:
            raise ImportError("failed to import loader plugin %s: %s" % (name, error))

    import_ = import_plugin

    def unwrap_exports(self, exports: Any) -> Any:
        if exports is None:
            return None
        default = getattr(exports, "default", None)
        if default is not None:
            return default
        if isinstance(exports, dict) and exports.get("default") is not None:
            return exports["default"]
        return exports

    unwrapExports = unwrap_exports

    def write(self) -> None:
        self.owner_ctx.emit("loader/config-update")

    def locate(self, fiber: Optional[Any] = None) -> Optional[str]:
        current = fiber or self.ctx.fiber
        while current is not None:
            entry = getattr(current, "entry", None)
            if entry is not None:
                return entry.id
            parent_ctx = getattr(current, "parent", None)
            next_fiber = getattr(parent_ctx, "fiber", None)
            if next_fiber is current:
                return None
            current = next_fiber
        return None

    def exit(self) -> None:
        return None

    def _legacy_load(self, rows: List[Dict[str, Any]], target_ctx: Any) -> None:
        group = self.root if target_ctx in (self.ctx, self.owner_ctx) else EntryGroup(target_ctx, self)
        for raw in rows:
            options = dict(raw)
            entry_id = self.ensure_id(options)
            if entry_id in self.store:
                raise TypeError("duplicate loader entry id: %s" % entry_id)
            entry = Entry(self, base_ctx=target_ctx)
            entry.parent = group
            entry.options = options
            self.store[entry_id] = entry
            group.data.append(entry.options)
            if entry.disabled:
                continue
            plugin = self.import_plugin(options["name"])
            if options.get("group"):
                nested_ctx = target_ctx.isolate(options.get("isolate") or {})
                entry.subgroup = EntryGroup(nested_ctx, self, owner_entry=entry)
                self._legacy_load(options.get("config") or [], nested_ctx)
                continue
            isolated = dict(target_ctx._isolated_keys)
            for service_name in (options.get("isolate") or {}):
                isolated[service_name] = self.isolation._access(entry, service_name, True)
            entry.ctx._isolated_keys = isolated
            entry.ctx._intercept_map.update(options.get("intercept") or {})
            materialized = entry._materialize(plugin)
            fiber = target_ctx.registry.plugin(
                materialized, config=entry._runtime_config(), parent_ctx=entry.ctx
            )
            fiber.entry = entry
            entry.fiber = fiber
            entry._plugin_source = plugin

    def load_from_dict(self, config_items: List[Dict[str, Any]],
                       target_ctx: Optional[Context] = None) -> Any:
        target = target_ctx or self.ctx
        for item in config_items:
            if not eval_condition(item.get("disabled", False), target):
                name = item.get("name") or item.get("id")
                if not item.get("group"):
                    self.import_plugin(name)
        try:
            import asyncio
            asyncio.get_running_loop()
        except RuntimeError:
            if target in (self.ctx, self.owner_ctx):
                return asyncio.run(self.root.update(config_items))
            self._legacy_load(config_items, target)
            return None
        self._legacy_load(config_items, target)
        return None

    def load_preset_file(self, filepath: str,
                         target_ctx: Optional[Context] = None) -> Any:
        if not os.path.isfile(filepath):
            raise FileNotFoundError("Preset file not found: %s" % filepath)
        with open(filepath, "r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=yaml.SafeLoader)
        if isinstance(data, dict) and "plugins" in data:
            data = data["plugins"]
        if not isinstance(data, list):
            raise ValueError("Invalid preset format in %s" % filepath)
        return self.load_from_dict(data, target_ctx)


PresetLoader = Loader


__all__ = [
    "Entry", "EntryGroup", "EntryNode", "EntryTree", "GlobalRealm", "Group",
    "IsolateManager", "JsExpr", "Loader", "LoaderAggregateError", "LocalRealm",
    "PresetLoader", "Realm", "eval_condition", "evaluate", "interpolate",
    "is_js_expr",
]
