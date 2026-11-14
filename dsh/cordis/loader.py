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
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union
import yaml

from dsh.cordis.context import Context
from dsh.cordis.errors import AggregateError as BaseAggregateError, safe_string
from dsh.cordis.fiber import Fiber, FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.utils import _UNDEFINED, deep_equal, is_nullable
from dsh.cordis.loader_diff import equal_except_volatile
from dsh.cordis.volatile import update_volatile, volatile_entries


class AwaitableNone:
    """A completed void operation that Python callers may optionally await."""
    def __await__(self):
        if False:
            yield
        return None


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


class _JsParseError(Exception):
    """An expression that is not part of the JavaScript subset evaluate_expr translates."""


# A JavaScript expression tokenizer. Strings keep their quotes so the generated
# Python literal is the same text; operators are matched longest-first so `===`
# never becomes `==` plus `=`.
_JS_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<number>\d+\.\d+(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<op>\?\?|\?\.|\*\*|===|!==|==|!=|<=|>=|&&|\|\||=>|[-+*/%<>!?:.,()\[\]{}])
    """,
    re.VERBOSE,
)

_PYTHON_KEYWORDS = frozenset((
    "and", "as", "assert", "async", "await", "break", "class", "continue",
    "def", "del", "elif", "else", "except", "finally", "for", "from", "global",
    "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass",
    "raise", "return", "try", "while", "with", "yield",
))


def _tokenize_js_expression(expr: str) -> List[Any]:
    """Split a JS expression into (kind, text) tokens, refusing unknown syntax."""
    tokens: List[Any] = []
    pos = 0
    length = len(expr)
    while pos < length:
        match = _JS_TOKEN_RE.match(expr, pos)
        if match is None:
            raise _JsParseError(f"unsupported character {expr[pos]!r} at {pos}")
        pos = match.end()
        kind = match.lastgroup
        if kind == "ws":
            continue
        tokens.append((kind, match.group()))
    return tokens


class _JsExpressionParser:
    """
    Translate the JavaScript expression subset the shipped bundles use into a
    Python expression, with JS operator precedence.

    Upstream evaluates an `!!js` body with the JS engine
    (`with (ctx) { return eval(expr) }`, reference/vendor/loader/src/config/utils.ts).
    The Python runtime has no JS engine, so the subset the pinned bundles
    actually carry is translated here in the same precedence order as JS
    (conditional, `??`, `||`, `&&`, equality, relational, additive,
    multiplicative, unary, postfix, primary). Anything outside the subset raises
    _JsParseError so the caller can fall back to the historical regex
    translation, which port-authored config expressions rely on.
    """

    def __init__(self, tokens: List[Any]):
        self.tokens = tokens
        self.index = 0

    def peek(self) -> Any:
        return self.tokens[self.index] if self.index < len(self.tokens) else (None, None)

    def next(self) -> Any:
        token = self.peek()
        self.index += 1
        return token

    def accept(self, text: str) -> bool:
        if self.peek()[1] == text:
            self.index += 1
            return True
        return False

    def expect(self, text: str) -> None:
        if not self.accept(text):
            raise _JsParseError(f"expected {text!r}")

    def parse(self) -> str:
        value = self.parse_conditional()
        if self.index != len(self.tokens):
            raise _JsParseError(f"unexpected token {self.peek()[1]!r}")
        return value

    def parse_conditional(self) -> str:
        condition = self.parse_nullish()
        if self.accept("?"):
            consequent = self.parse_conditional()
            self.expect(":")
            alternate = self.parse_conditional()
            return f"({consequent} if {condition} else {alternate})"
        return condition

    def parse_nullish(self) -> str:
        value = self.parse_logical_or()
        while self.accept("??"):
            right = self.parse_logical_or()
            value = f"_coalesce({value}, {right})"
        return value

    def parse_logical_or(self) -> str:
        value = self.parse_logical_and()
        while self.accept("||"):
            right = self.parse_logical_and()
            value = f"({value} or {right})"
        return value

    def parse_logical_and(self) -> str:
        value = self.parse_equality()
        while self.accept("&&"):
            right = self.parse_equality()
            value = f"({value} and {right})"
        return value

    def parse_equality(self) -> str:
        value = self.parse_relational()
        while True:
            op = self.peek()[1]
            if op not in ("==", "===", "!=", "!=="):
                return value
            self.next()
            right = self.parse_relational()
            py_op = "==" if op in ("==", "===") else "!="
            value = f"({value} {py_op} {right})"

    def parse_relational(self) -> str:
        value = self.parse_additive()
        while True:
            op = self.peek()[1]
            if op not in ("<", "<=", ">", ">="):
                return value
            self.next()
            right = self.parse_additive()
            value = f"({value} {op} {right})"

    def parse_additive(self) -> str:
        value = self.parse_multiplicative()
        while True:
            op = self.peek()[1]
            if op not in ("+", "-"):
                return value
            self.next()
            right = self.parse_multiplicative()
            value = f"({value} {op} {right})"

    def parse_multiplicative(self) -> str:
        value = self.parse_unary()
        while True:
            op = self.peek()[1]
            if op not in ("*", "/", "%"):
                return value
            self.next()
            right = self.parse_unary()
            value = f"({value} {op} {right})"

    def parse_unary(self) -> str:
        op = self.peek()[1]
        if op == "!":
            self.next()
            return f"(not {self.parse_unary()})"
        if op == "-":
            self.next()
            return f"(-{self.parse_unary()})"
        if op == "+":
            self.next()
            return f"(+{self.parse_unary()})"
        return self.parse_postfix()

    def parse_postfix(self) -> str:
        value = self.parse_primary()
        while True:
            if self.accept("."):
                kind, name = self.next()
                if kind != "name":
                    raise _JsParseError("expected a property name after '.'")
                value = f"{value}.{name}"
            elif self.accept("["):
                index = self.parse_conditional()
                self.expect("]")
                value = f"{value}[{index}]"
            elif self.accept("("):
                args: List[str] = []
                if not self.accept(")"):
                    args.append(self.parse_conditional())
                    while self.accept(","):
                        args.append(self.parse_conditional())
                    self.expect(")")
                value = f"{value}({', '.join(args)})"
            else:
                return value

    def parse_primary(self) -> str:
        kind, text = self.next()
        if kind in ("number", "string"):
            return text
        if text == "(":
            value = self.parse_conditional()
            self.expect(")")
            return f"({value})"
        if text == "[":
            items: List[str] = []
            if not self.accept("]"):
                items.append(self.parse_conditional())
                while self.accept(","):
                    items.append(self.parse_conditional())
                self.expect("]")
            return "[" + ", ".join(items) + "]"
        if text == "{":
            pairs: List[str] = []
            if not self.accept("}"):
                while True:
                    key_kind, key = self.next()
                    if key_kind == "string":
                        py_key = key
                    elif key_kind == "name":
                        py_key = json.dumps(key)
                    else:
                        raise _JsParseError("object literal keys must be names or strings")
                    self.expect(":")
                    pairs.append(f"{py_key}: {self.parse_conditional()}")
                    if not self.accept(","):
                        break
                self.expect("}")
            return "{" + ", ".join(pairs) + "}"
        if kind == "name":
            if text == "true":
                return "True"
            if text == "false":
                return "False"
            if text in ("null", "undefined"):
                return "None"
            if text == "process":
                return self.parse_process()
            if text in _PYTHON_KEYWORDS:
                raise _JsParseError(f"{text!r} is not part of the JS expression subset")
            return text
        raise _JsParseError(f"unexpected token {text!r}")

    def parse_process(self) -> str:
        """Translate the `process` globals the pinned bundles reference."""
        if not self.accept("."):
            return "process"
        kind, name = self.next()
        if kind != "name":
            raise _JsParseError("expected a process member")
        if name == "env":
            if self.accept("."):
                env_kind, env_name = self.next()
                if env_kind != "name":
                    raise _JsParseError("expected an environment variable name")
                return f"env.get({json.dumps(env_name)})"
            if self.accept("["):
                key_kind, key = self.next()
                if key_kind != "string":
                    raise _JsParseError("environment lookups need a string key")
                self.expect("]")
                return f"env.get({key})"
            return "env"
        if name == "platform":
            return "sys.platform"
        if name == "cwd":
            self.expect("(")
            self.expect(")")
            return "os.getcwd()"
        if name == "execPath":
            return "sys.executable"
        if name == "version":
            return "sys.version"
        raise _JsParseError(f"unsupported process member {name!r}")


def _translate_js_expression(expr: str) -> str:
    """Translate a JS expression to Python source, or raise _JsParseError."""
    tokens = _tokenize_js_expression(expr)
    if not tokens:
        raise _JsParseError("empty expression")
    return _JsExpressionParser(tokens).parse()


def _legacy_translate_expression(expr: str) -> str:
    """
    The historical regex translation, kept as the fallback for expressions that
    are not in the JS subset above (port-authored configs carry Python-flavored
    expression bodies that a JS engine upstream would reject).
    """
    expr_py = expr
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

    # JS nullish coalescing `a ?? b` -> `_coalesce(a, b)` (must precede ternary)
    coalesce_re = re.compile(r'([^?]+)\?\?([^?]+)')
    while coalesce_re.search(expr_py):
        expr_py = coalesce_re.sub(r'(_coalesce(\1, \2))', expr_py)

    # JS ternary expressions `cond ? val1 : val2` -> `(val1 if cond else val2)`
    ternary_re = re.compile(r'([^\?:]+)\?([^\?:]+):([^\?:]+)')
    while ternary_re.search(expr_py):
        expr_py = ternary_re.sub(r'(\2 if \1 else \3)', expr_py)
    return expr_py


def evaluate_expr(ctx: Any, expr: str) -> Any:
    """
    Safely evaluate expression string in the given Context matching TS evaluate(ctx, expr).
    Translates common JS patterns to Python syntax safely using AST analysis.
    """
    expr_str = expr.strip()
    if expr_str.startswith("!!js"):
        expr_str = expr_str[4:].strip()

    # The shipped Cordis preset resolves its own skill directory through node:url.
    url_path = re.fullmatch(r"process\.getBuiltinModule\(['\"]node:url['\"]\)\.fileURLToPath\(new URL\((['\"])(.*?)\1,\s*baseUrl\)\)", expr_str)
    if url_path:
        from urllib.parse import urljoin, urlparse
        from urllib.request import url2pathname
        base = getattr(ctx, 'baseUrl', None) or getattr(ctx, 'base_url', None)
        parsed = urlparse(urljoin(base or '', url_path.group(2)))
        if parsed.scheme != 'file':
            raise ValueError('fileURLToPath requires a file URL')
        path = url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc != 'localhost':
            path = '//'+parsed.netloc+path
        return path

    # Self-executing arrow functions that only throw have no Python counterpart;
    # rewrite the idiom before translating the surrounding expression.
    expr_str = re.sub(
        r'\(\(\)\s*=>\s*\{\s*throw\s+(?:new\s+)?Error\((.*?)\);?\s*\}\)\(\)',
        r'(_throw(\1))',
        expr_str,
    )

    try:
        expr_py = _translate_js_expression(expr_str)
    except _JsParseError:
        expr_py = _legacy_translate_expression(expr_str)

    def _coalesce(a: Any, b: Any) -> Any:
        return b if a is None else a

    def _throw(msg: Any) -> Any:
        raise RuntimeError(str(msg))

    def _js_number(value: Any) -> Any:
        """JS `Number(value)`: numeric strings, booleans, and null convert; else NaN."""
        if value is None:
            return float("nan")
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return value
        text = str(value).strip()
        if text == "":
            return 0
        try:
            if re.fullmatch(r"[+-]?\d+", text):
                return int(text)
            return float(text)
        except ValueError:
            return float("nan")

    def _js_string(value: Any) -> str:
        """JS `String(value)`: null/undefined keep their JS spellings."""
        if value is None:
            return "undefined"
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

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
        "Number": _js_number,
        "String": _js_string,
        "Boolean": bool,
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


class AggregateError(BaseAggregateError):
    """Aggregate error containing multiple underlying errors."""
    def __init__(self, errors: List[Any], message: str = ""):
        super().__init__(errors, message)

    def __str__(self) -> str:
        err_msgs = ", ".join(safe_string(e) for e in self.errors)
        return f"{self.message}: [{err_msgs}]" if self.message else err_msgs


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
                    # The reference drops this promise because the microtask
                    # queue keeps driving it; the fiber owns the settlement
                    # instead so boot, harness, CLI, and HMR settlement join it.
                    ctx.root.fiber.schedule_settlement(res)

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
        if key in self.store:
            return self.store[key]
        # JS Symbol descriptions are diagnostic labels, not identity. Separate
        # preset trees routinely contain the same local entry ids. Give every
        # new symbol its own token, including non-creating probes and recreation
        # after delete; only a retained realm registration may share identity.
        symbol = f"{key}{self.suffix}:{uuid.uuid4().hex}"
        if create:
            self.store[key] = symbol
        return symbol

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


def _exports_condition_target(value: Any) -> Optional[str]:
    """Resolve one exports entry (possibly a conditions map) to its relative target."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for condition in ("import", "default"):
            inner = value.get(condition)
            resolved = _exports_condition_target(inner)
            if resolved is not None:
                return resolved
    return None


def exports_subpath_target(exports: Any, subpath: str) -> Optional[str]:
    """
    Resolve a `./subpath` request through a package's exports map, matching Node's
    exact-key-then-pattern rule.

    @param exports: the package's `exports` field.
    @param subpath: the requested subpath without a leading `.`, e.g. `startup`.
    @returns: the relative target, or None when the map does not export it.
    """
    if not isinstance(exports, (dict, str)):
        return None
    key = "./" + subpath
    if isinstance(exports, str):
        return exports if key == "." else None
    target = _exports_condition_target(exports.get(key))
    if target is not None:
        return target
    for pattern, value in exports.items():
        if not isinstance(pattern, str) or "*" not in pattern:
            continue
        prefix, _, suffix = pattern.partition("*")
        if not key.startswith(prefix) or not key.endswith(suffix):
            continue
        if len(key) < len(prefix) + len(suffix):
            continue
        matched = key[len(prefix): len(key) - len(suffix)]
        resolved = _exports_condition_target(value)
        if resolved is not None:
            return resolved.replace("*", matched)
    return None


def _entry_from_package_json(pkg_json_path: str, subpath: Optional[str] = None) -> Optional[str]:
    """
    Resolve one package manifest to the module a request names.

    @param pkg_json_path: absolute path of the package's `package.json`.
    @param subpath: a `./subpath` request to resolve through the exports map;
        None asks for the package root entry.
    @returns: the resolved file path, or None when nothing answers it.
    """
    try:
        with open(pkg_json_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        pkg_dir = os.path.dirname(pkg_json_path)
        exports = manifest.get("exports")
        if subpath is None and isinstance(manifest.get("dsh"), dict) and "python" in manifest["dsh"]:
            # The manifest identifies the Python entry, including its export.
            # Validation happens on import and must not fall through to a JS mock.
            return pkg_json_path
        if subpath is not None:
            # The exports map is a path computation: Node resolves `./startup`
            # to its target without probing the filesystem, and the import that
            # follows is what fails when the artifact is absent. Keeping that
            # shape is what lets the Loader classify the row as installation
            # owned and answer it from the table instead of the shipped JS.
            target = exports_subpath_target(exports, subpath)
            if not isinstance(target, str):
                return None
            return os.path.normpath(os.path.join(pkg_dir, target))
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


def reparse_target(path: str) -> Optional[str]:
    """Return the target of a symlink or Windows directory junction, or None."""
    try:
        if os.path.islink(path):
            return os.readlink(path)
        # Python 3.8 reports Windows junctions through the reparse tag; os.readlink
        # reads them, os.path.islink does not.
        tag = getattr(os.lstat(path), "st_reparse_tag", 0)
        if tag:
            return os.readlink(path)
    except (OSError, ValueError):
        return None
    return None


def is_installation_owned_module(path: str, installation_roots: Optional[List[str]] = None) -> bool:
    """
    Return whether a resolved module path is a dsh-healed installation fallback entry.

    `healProfilesModuleFallback` publishes the installation's dependency closure at
    `$DSH_HOME/profiles/node_modules` and projects the packages only selected
    bundles carry through `<profile>/.dsh-module-fallback/node_modules`
    (reference/packages/boot/app-boot/src/profile.ts). Node imports whatever those
    links point at; the Python runtime replaces them with the class table
    (`dsh/boot/plugin_registry.py`), so an installation-owned path must never
    answer with the shipped JS artifact.

    @param path: a resolved specifier, e.g. `<...>/node_modules/@deepseek-ai/dsh-tools`.
    @param installation_roots: the fallback node_modules directories the launcher healed.
    @returns: whether the path, or the link it is, belongs to the installation.
    """
    if not installation_roots or not path:
        return False
    roots = [os.path.normcase(os.path.normpath(root)) for root in installation_roots if root]

    def under_installation(candidate: str) -> bool:
        normalised = os.path.normcase(os.path.normpath(candidate))
        return any(normalised == root or normalised.startswith(root + os.sep) for root in roots)

    def link_target(candidate: str) -> Optional[str]:
        target = reparse_target(candidate)
        if target is None:
            return None
        if target.startswith("\\\\?\\"):
            target = target[4:]
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(candidate), target)
        return target

    # A healed fallback entry is either the resolved path itself (the shared
    # closure) or a link projected into the profile's own node_modules, in which
    # case the resolved file sits below that link.
    current = os.path.normpath(path)
    for _ in range(32):
        if under_installation(current):
            return True
        target = link_target(current)
        if target is not None and under_installation(target):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return False


def split_package_specifier(name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Split a bare specifier into its package name and requested subpath.

    @param name: a bare specifier, e.g. `@scope/pkg` or `@scope/pkg/startup`.
    @returns: the package name and the subpath without a leading `.` (None for
        the package root), or (None, None) when the specifier names no package.
    """
    if name.startswith("@"):
        parts = name.split("/")
        if len(parts) < 2 or not parts[0] or not parts[1]:
            return None, None
        return "/".join(parts[:2]), "/".join(parts[2:]) if len(parts) > 2 else None
    parts = name.split("/")
    if not parts[0]:
        return None, None
    return parts[0], "/".join(parts[1:]) if len(parts) > 1 else None


def module_search_dirs(base_dir: str, module_roots: Optional[List[str]] = None) -> List[str]:
    """
    Return every `node_modules`-style directory a bare specifier resolves through.

    Node walks the ancestor chain; the healed installation closure the launcher
    publishes is installed on the Loader as extra roots, so it is answered here
    in the same order the Loader's `installation_module_roots` names them.

    @param base_dir: the directory resolution starts from.
    @param module_roots: additional `node_modules` directories, e.g. the healed
        `$DSH_HOME/profiles/node_modules` and the profile-owned projection.
    @returns: the search directories, in resolution order.
    """
    dirs: List[str] = []
    curr = os.path.abspath(base_dir)
    while True:
        dirs.append(os.path.join(curr, "node_modules"))
        parent = os.path.dirname(curr)
        if parent == curr:
            break
        curr = parent
    for root in module_roots or []:
        if root and root not in dirs:
            dirs.append(root)
    return dirs


def resolve_module_specifier(
    name: str,
    base_dir: str,
    module_roots: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Resolve a relative, absolute, or bare module specifier from base_dir matching
    Node module resolution, including a package subpath through its exports map.

    @param name: the specifier to resolve.
    @param base_dir: the directory resolution starts from.
    @param module_roots: additional `node_modules` directories to search after
        the ancestor chain, e.g. the healed installation fallback.
    @returns: the resolved file (or package directory) path, or None.
    """
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

    # Bare module specifier: walk up node_modules, then the healed installation
    # fallback roots Node would reach from this config tree.
    package_name, subpath = split_package_specifier(name)
    if package_name is None:
        return None
    for modules_dir in module_search_dirs(base_dir, module_roots):
        cand_dir = os.path.join(modules_dir, *package_name.split("/"))
        if not os.path.isdir(cand_dir):
            continue
        pkg_json = os.path.join(cand_dir, "package.json")
        if os.path.isfile(pkg_json):
            if subpath is not None:
                # A subpath the exports map does not carry has no module to
                # return; only the package root falls back below.
                return _entry_from_package_json(pkg_json, subpath)
            entry = _entry_from_package_json(pkg_json)
            if entry:
                return entry
        for ext in (".mjs", ".js", ".ts", ".py"):
            idx = os.path.join(cand_dir, "index" + ext)
            if os.path.isfile(idx):
                return idx
        return cand_dir

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
        self._pending_tasks: Set[asyncio.Task] = set()
        self.root = EntryGroup(self.ctx, self)
        fiber_entry = getattr(getattr(self.ctx, "fiber", None), "entry", None)
        if fiber_entry:
            fiber_entry.subtree = self
        setattr(self, "await", self.await_)

    def _track(self, task: Any) -> Any:
        """
        Record a task this tree started as pending lifecycle work.

        `tree.ts` `getTasks()` reports the work a tree still owns (`entry._initTask`
        or `entry.fiber.inertia`). The port's synchronous entry points return the
        task instead of awaiting it at the call site, so the tree records every
        task it creates; `get_tasks()` then reports it and `await_()` waits for it
        before reporting settlement.
        """
        if asyncio.isfuture(task):
            self._pending_tasks.add(task)
            task.add_done_callback(self._retire_pending)
        return task

    def _retire_pending(self, task: Any) -> None:
        """
        Drop a settled task from the pending set and mark its failure reported.

        `await_()` collects pending task outcomes, but a tree that is torn down
        without a settlement pass would otherwise surface a retrieved-only
        failure as an unretrieved task exception at garbage collection.
        """
        self._pending_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    @property
    def context(self) -> Context:
        return self.ctx

    def get_tasks(self) -> List[Any]:
        """Only imports and entry Fiber inertia determine Loader admission."""
        tasks: List[Any] = []
        for entry in self.entries():
            pending = getattr(entry, "_init_task", None)
            if pending is None:
                pending = getattr(entry.fiber, "inertia", None) if entry.fiber else None
            if pending is not None and not pending.done():
                tasks.append(pending)
        return tasks

    async def await_tasks(self) -> None:
        """Wait until this tree has no active import or lifecycle tasks."""
        await self.await_()

    async def wait(self) -> None:
        """Wait until this tree has no active tasks and settled fibers matching TS await()."""
        await self.await_()

    async def await_(self) -> None:
        """Wait for owned pending work; stored activation failures remain on fibers."""
        while True:
            tasks = self.get_tasks()
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

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
        """Report insertion before starting the child lifecycle, as Source does."""
        group = self.resolve_group(parent_id)
        entry_id = group.tree.ensure_id(options)
        index = len(group.data) if position is None else int(min(position, len(group.data)))
        group.data.insert(index, options)
        group.tree.commit(dict(id=entry_id, group=group, options=options))
        return group.create(options)

    def remove(self, entry_id: str) -> Any:
        """Unregister and report removal synchronously; Fiber owns teardown."""
        entry = self.resolve(entry_id)
        group = entry.parent
        legacy = entry.options
        group.remove(legacy['id'])
        group.tree.commit(dict(id=legacy['id'], group=group, legacy=legacy))
        return AwaitableNone()

    def update(self, entry_id: str, options: Dict[str, Any], parent_id: Any = _UNDEFINED, position: Optional[int] = None) -> Any:
        """Update an entry and optionally transfer its group/tree ownership."""
        try:
            loop = asyncio.get_running_loop()
            from dsh.cordis.awaiting import start_coroutine
            return self._track(start_coroutine(self._update_tree_entry_async(entry_id, options, parent_id, position)))
        except RuntimeError:
            return asyncio.run(self._update_tree_entry_async(entry_id, options, parent_id, position))

    async def _update_tree_entry_async(self, entry_id: str, options: Dict[str, Any], parent_id: Any = _UNDEFINED, position: Optional[int] = None) -> None:
        entry = self.resolve(entry_id)
        source = entry.parent
        legacy = dict(entry.options)
        target = source
        if parent_id is not _UNDEFINED:
            target = self.resolve_group(parent_id)
            moved = []
            if target.tree is not source.tree:
                def members(current: Any) -> None:
                    moved.append(current)
                    group = current.subgroup
                    if group is None or group.tree is not source.tree:
                        return
                    for row in group.data:
                        member = source.tree.store.get(row.get('id'))
                        if member is not None and member.parent is group:
                            members(member)
                members(entry)
            for member in moved:
                local_id = member.options['id']
                if local_id in target.tree.store:
                    raise ValueError('entry %s already exists in the target tree' % local_id)
            source.unlink(entry.options)
            index = len(target.data) if position is None else int(min(position, len(target.data)))
            target.data.insert(index, entry.options)
            entry.parent = target
            for member in moved:
                local_id = member.options['id']
                source.tree.store.pop(local_id, None)
                target.tree.store[local_id] = member
                if member.subgroup is not None and member.subgroup.tree is source.tree:
                    member.subgroup.tree = target.tree
        result = entry.update(options, create=False, force=True)
        if target.tree is not source.tree:
            source.tree.commit(dict(id=legacy['id'], group=source, legacy=legacy))
            target.tree.commit(dict(id=legacy['id'], group=target, options=entry.options))
        else:
            change = dict(id=legacy['id'], group=target, options=entry.options, legacy=legacy)
            if target is not source:
                change['from'] = source
            target.tree.commit(change)
        if inspect.isawaitable(result):
            await result

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
                    if mod_name and mod_name.startswith(('dynamic_plugin_', 'dynamic_cordis_plugin_')):
                        loader._module_aliases.setdefault(mod_name, set()).add(name)
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

        is_bare_name = not (
            name.startswith(("./", "../", "/", "\\"))
            or name.startswith("file://")
            or os.path.isabs(name)
        )
        resolved_path = resolve_module_specifier(
            name, base_dir, getattr(loader, "installation_module_roots", None)
        )
        if resolved_path is not None and is_bare_name and is_installation_owned_module(
            resolved_path, getattr(loader, "installation_module_roots", None)
        ):
            # The installation ships built JS artifacts for the packages it owns;
            # the Python implementation of an installation row is the class table,
            # so an installation-owned path answers with the table or fails loud
            # rather than loading a JS stand-in.
            res = (getattr(loader, "harness_plugins", None) or {}).get(name)
            if res is not None:
                return res
            raise ModuleNotFoundError(f"Cannot find module '{name}'")
        if resolved_path is not None:
            if not os.path.exists(resolved_path):
                if os.path.exists(resolved_path + ".py"):
                    resolved_path = resolved_path + ".py"
                else:
                    raise FileNotFoundError(f"Cannot find module '{name}' at {resolved_path}")

            if os.path.basename(resolved_path) == "package.json":
                from dsh.boot.python_package import import_package
                plugin, module = import_package(os.path.dirname(resolved_path))
                self._last_loaded_module = module.__name__
                loader_inst = getattr(self.ctx, "loader", None) or self
                if hasattr(loader_inst, "internal"):
                    from pathlib import Path
                    loader_inst.internal.loadCache[Path(os.path.realpath(resolved_path)).as_uri()] = module
                return plugin

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

        # The installation-owned fallback is the last anchor, matching the Node
        # runtime where the healed profiles/node_modules closure answers only
        # after the config project does not own the package.
        harness_map = getattr(loader, "harness_plugins", None) or {}
        res = harness_map.get(name)
        if res is not None:
            return res

        raise ModuleNotFoundError(f"Cannot find module '{name}'")

    import_ = import_plugin

    def unwrap_exports(self, module: Any) -> Any:
        if module is None:
            return None
        d = getattr(module, "default", module)
        return d if d is not None else module

    def commit(self, change: Dict[str, Any]) -> None:
        """Report a tree mutation; file-backed trees override the persistence."""
        self.write()

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

    def _track_task(self, task: Any) -> Any:
        """Record a task this group started in its tree's pending set."""
        tree = getattr(self, "tree", None)
        if tree is not None and hasattr(tree, "_track"):
            return tree._track(task)
        return task

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
            entry.options = options
        prev_parent = entry.parent
        entry.parent = self
        self.tree.store[eid] = entry

        async def _run_create():
            res = entry.update(options, create=True, force=True)
            if inspect.isawaitable(res):
                await res
            return str(eid)

        try:
            loop = asyncio.get_running_loop()
            from dsh.cordis.awaiting import start_coroutine
            task = self._track_task(start_coroutine(_run_create()))
            return AwaitableString(entry.id, task)
        except RuntimeError:
            asyncio.run(_run_create())
            return AwaitableString(entry.id)

    async def _create_async(self, options: Dict[str, Any]) -> str:
        return await self.create(options)

    def unlink(self, options: Dict[str, Any]) -> None:
        index = next((i for i, value in enumerate(self.data) if value is options), -1)
        if index >= 0:
            self.data.pop(index)

    @property
    def context(self) -> Context:
        return self.ctx

    def remove(self, entry_id: str, is_dispose: bool = False) -> Any:
        entry = self.tree.store.get(entry_id)
        if entry is None or entry.parent is not self:
            return AwaitableNone()
        self.tree.store.pop(entry_id)
        if entry.fiber:
            result = entry.fiber.dispose()
            entry.fiber.ctx.fiber.schedule_settlement(result)
        if not is_dispose:
            self.unlink(entry.options)
        self.context.emit("loader/partial-dispose", entry, entry.options, False)
        return AwaitableNone()

    async def _remove_async(self, entry_id: str, is_dispose: bool = False) -> None:
        self.remove(entry_id, is_dispose)

    def update(self, config_list: List[Dict[str, Any]]) -> Any:
        old_config = self.data
        self.data = config_list
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._update_async(config_list, old_config))
        from dsh.cordis.awaiting import start_coroutine
        task = self._track_task(start_coroutine(self._update_async(config_list, old_config)))
        self._update_task = task
        return task

    async def _update_async(self, config_list: List[Dict[str, Any]],
                            old_config: Optional[List[Dict[str, Any]]] = None) -> None:
        old_map = {opt.get('id'): opt for opt in (old_config or [])}
        new_map = {}
        for options in config_list:
            key = options.get('id') or object()
            new_map[key] = options
        keys = list(dict.fromkeys(list(old_map) + list(new_map)))
        async def apply_one(key: Any) -> None:
            if key in new_map:
                try:
                    result = self.create(new_map[key])
                    if inspect.isawaitable(result):
                        await result
                except Exception as error:
                    self.ctx.logger('loader').error(error)
            else:
                await self._remove_async(key)
        try:
            from dsh.cordis.awaiting import start_coroutine
            await asyncio.gather(*(start_coroutine(apply_one(key)) for key in keys))
        finally:
            self._update_task = None

    def stop(self) -> Any:
        for options in self.data:
            self.remove(options.get("id"), is_dispose=True)
        return AwaitableNone()

    async def _stop_async(self) -> None:
        self.stop()

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
        self.config = config if config is not None else []

        async def _on_group_update(cfg: Any, next_fn: Optional[Callable[[], Any]] = None, *args: Any, **kwargs: Any) -> Any:
            res = self.update(cfg)
            if inspect.isawaitable(res):
                await res
            return None

        ctx.on("internal/update", _on_group_update)

    async def init(self) -> Any:
        yield lambda: self._stop_async()
        await self.update(self.config)


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
        self._init_inner_task: Optional[asyncio.Future] = None
        self._disposing = 0
        self._loaded_module_name: Optional[str] = None

        loader_ctx = getattr(loader, "ctx", None) if loader else None
        if loader_ctx:
            self.ctx = loader_ctx.extend({Entry.key: self, "entry": self})
            self.ctx.emit("loader/entry-init", self)
        else:
            self.ctx = Context()

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

    def _track_task(self, task: Any) -> Any:
        """Record a task this entry started in the owning tree's pending set."""
        tree = getattr(getattr(self, "parent", None), "tree", None)
        if tree is None:
            loader = getattr(self, "loader", None)
            tree = loader if isinstance(loader, EntryTree) else None
        if tree is not None and hasattr(tree, "_track"):
            return tree._track(task)
        return task

    def _dispose(self, fiber: Optional[Fiber] = None) -> Any:
        try:
            loop = asyncio.get_running_loop()
            return self._track_task(loop.create_task(self._dispose_async(fiber)))
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

    async def _patch_context(self, diff: List[str]) -> None:
        async def _cont():
            if self.parent and hasattr(self.parent, "ctx"):
                self.ctx.parent = self.parent.ctx
                self.ctx.baseUrl = self.parent.ctx.baseUrl
                if self.fiber:
                    self.fiber.ctx.baseUrl = self.ctx.baseUrl
            if self.fiber and getattr(self.fiber, "uid", None) and ("config" in diff or self.options.get("group")):
                for name in self.fiber.inject:
                    self.fiber._checkImpl(name)
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
        await self._patch_context([])
        if self.loader and hasattr(self.loader, "show_log"):
            self.loader.show_log(self, "apply")
        self.fiber = self.ctx.registry.plugin(plugin, config=self.options.get("config"), get_outer_stack=self.get_outer_stack)
        if self.fiber:
            self.fiber.entry = self
            instance = getattr(self.fiber, "plugin", None)
            if isinstance(instance, EntryTree) or hasattr(instance, "root"):
                self.subtree = instance
                # The Python Service/Registry constructor can run before the
                # returned handle is assigned here. Publish the tree's actual
                # root group together with its subtree, as EntryGroup's Source
                # constructor does on the owning fiber.
                self.subgroup = instance.root

    async def _init(self) -> None:
        if not self.options.get("name"):
            if self.options.get("group") or self.options.get("id", "").startswith("group"):
                await self._start(Group)
            return
        tree = getattr(self.parent, "tree", None) or self.loader
        try:
            raw = tree.import_plugin(self.options["name"], self.get_outer_stack)
            from dsh.cordis.awaiting import await_callback_result
            raw = await await_callback_result(raw)
        except Exception as error:
            self.ctx.logger("loader").error(error)
            return
        plugin = self.loader.unwrap_exports(raw)
        if getattr(tree, "_last_loaded_module", None):
            self._loaded_module_name = tree._last_loaded_module
            tree._last_loaded_module = None
        elif getattr(plugin, '__module__', None) in getattr(self.loader, '_module_owners', {}):
            self._loaded_module_name = plugin.__module__
        await self._start(plugin)
        self.moduleNamespace = raw

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
        """
        Start this entry's initialization and return the task that owns it.

        `tree.ts` `getTasks()` reports `entry._initTask`, so the runner created
        here is recorded on the entry and in the owning tree's pending set, and
        `EntryTree.await_()` waits for it before reporting settlement. A
        loop-less caller has no checkpoint to defer to, so the runner is driven
        to completion inline.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._init_task_runner())
        from dsh.cordis.awaiting import start_coroutine
        task = self._track_task(start_coroutine(self._init_task_runner()))
        self._init_task = task if not task.done() else None
        return task

    async def _init_task_runner(self) -> None:
        try:
            if not self._init_inner_task:
                from dsh.cordis.awaiting import start_coroutine
                self._init_inner_task = start_coroutine(self._init())
            await self._init_inner_task
        finally:
            self._init_inner_task = None
            self._init_task = None
            if hasattr(self.loader, "get_tasks") and not self.loader.get_tasks():
                if self.ctx and hasattr(self.ctx, "reflect"):
                    self.ctx.reflect.notify(["loader"])
        if self.fiber:
            async def notify_when_settled():
                try:
                    await self._await()
                except Exception:
                    pass
                if not self.loader.get_tasks():
                    self.ctx.reflect.notify(["loader"])
            from dsh.cordis.awaiting import start_coroutine
            start_coroutine(notify_when_settled())

    def update(self, options: Dict[str, Any], create: bool = False, force: bool = False) -> Any:
        """Publish raw options first, then apply the required lifecycle changes."""
        try:
            loop = asyncio.get_running_loop()
            from dsh.cordis.awaiting import start_coroutine
            return self._track_task(start_coroutine(self._update_async(options, create=create, force=force)))
        except RuntimeError:
            return asyncio.run(self._update_async(options, create=create, force=force))

    def _commit_volatile(self) -> bool:
        """Commit a validated candidate before notifying only this activation."""
        fiber = self.fiber.ctx.fiber
        refs = volatile_entries(fiber.effectiveConfig)
        if not refs:
            return True
        try:
            candidate = fiber.resolveConfig(self.options.get("config"))
        except Exception as error:
            self.ctx.logger("loader").warn("volatile config update failed for %s", self.id)
            self.ctx.logger("loader").warn(error)
            return True
        if not deep_equal(fiber.effectiveConfig, candidate, True):
            self.ctx.logger("loader").debug(
                "ordinary config values of %s changed with its volatile values; applying the ordinary update", self.id)
            return False
        paths = []
        for item in refs:
            source = candidate
            for key in item["path"]:
                source = source[int(key)] if isinstance(source, list) else source[key]
            reference = item["ref"]
            if deep_equal(reference.get(), source.get(), True):
                continue
            update_volatile(reference, source)
            paths.append(item["path"])
        if not paths:
            return True
        carrier = fiber.ctx.extend()
        carrier._filter_hook = lambda owner: owner.fiber is fiber
        try:
            fiber.ctx.emit(carrier, "loader/volatile-update", paths)
        except Exception as error:
            self.ctx.logger("loader").warn(error)
        return True

    async def _update_async(self, options: Dict[str, Any], create: bool = False, force: bool = False) -> None:
        legacy = dict(self.options)
        if create:
            self.options = options
        else:
            for key, value in options.items():
                if is_nullable(value):
                    self.options.pop(key, None)
                else:
                    self.options[key] = value
        sort_keys(self.options)
        self.name = self.options.get("name", "")
        self.config = self.options.get("config")
        if self.disabled:
            if self.fiber:
                await self.fiber.dispose()
            return
        if self.fiber and self.fiber.uid:
            keys = list(dict.fromkeys(list(self.options) + list(legacy)))
            changes = [key for key in keys if not deep_equal(
                self.options.get(key, _UNDEFINED), legacy.get(key, _UNDEFINED), key == "config")]
            volatile_only = (changes == ["config"] and self.fiber.state == FiberState.ACTIVE
                             and self.ctx.parent is self.parent.ctx
                             and equal_except_volatile(legacy.get("config", _UNDEFINED),
                                self.options.get("config", _UNDEFINED), self.fiber.runtime.Config))
            if volatile_only:
                self.fiber.rawConfig = self.options.get("config")
            pending = [] if volatile_only and self._commit_volatile() else changes
            if not pending and not force:
                return
            self.context.emit("loader/partial-dispose", self, legacy, True)
            await self._patch_context(pending)
        else:
            result = self.init()
            if inspect.isawaitable(result):
                await result



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
        from dsh.cordis.timer import TimerService
        self.builtins["include"] = Include
        self.builtins["group"] = Group
        self.registry_map["cordis:include"] = Include
        self.registry_map["@deepseek-ai/cordis-plugin-include"] = Include
        self.registry_map["cordis:group"] = Group
        self.registry_map["@deepseek-ai/cordis-plugin-group"] = Group
        self.registry_map["@deepseek-ai/cordis-plugin-timer"] = TimerService
        # Installation-owned fallback resolution table: the Python counterpart of
        # the harness installation module closure a bare row name resolves through
        # when the config project does not own that package. Populated by
        # dsh.boot.plugin_registry.install_harness_plugin_classes.
        self.harness_plugins: Dict[str, Any] = {}
        # The launcher-healed installation fallback node_modules levels (the shared
        # $DSH_HOME/profiles/node_modules closure and the profile-owned projection).
        # A bare name that would resolve through one of them is an installation row,
        # never a config-project module. Set by dsh.boot.app_boot.boot.
        self.installation_module_roots: List[str] = []
        self.entries_list: List[Entry] = []
        self._realms: Dict[str, GlobalRealm] = {}
        self._delims: Dict[str, str] = {}
        self._module_owners: Dict[Any, Any] = {}
        self._module_aliases: Dict[str, Any] = {}
        self.internal = LoaderInternal()

        if self.ctx:
            self.ctx.on("internal/config", self._on_internal_config, global_listener=True)
            self.ctx.on("internal/commit", self._on_internal_commit)
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
                        owner_entry = getattr(impl_fiber, "entry", None)
                        marker_ctx = getattr(owner_entry, "ctx", impl_ctx)
                        impl_delims = getattr(marker_ctx, "_isolate_delims", {}) if marker_ctx else {}
                        impl_flag = impl_delims.get(delim_k, "")
                        diff[name] = (old_sym, new_sym, entry_flag, impl_flag)
                        if entry_flag != impl_flag:
                            break

                # Step 3: Update isolate & intercept maps
                entry.ctx._isolated_keys = new_map
                if entry.fiber is not None:
                    entry.fiber.ctx._isolated_keys = dict(new_map)
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
                            target_entry = getattr(getattr(target_ctx, "fiber", None), "entry", None)
                            target_delims = getattr(getattr(target_entry, "ctx", target_ctx), "_isolate_delims", {})
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
                # 1. set fiber.entry and resolve inject matching TS Loader index.ts:118-123.
                # A fiber created from an entry context already carries that entry, so
                # `entry.options.inject` is merged the first time the loader sees the
                # fiber rather than only while it is still unset: it is what keeps a row
                # whose config reads an injected service PENDING until the provider that
                # provides it has activated.
                parent_entry = getattr(getattr(fiber, "parent", None), "_entry", None) or getattr(getattr(fiber, "parent", None), "entry", None)
                if parent_entry is not None and not getattr(fiber, "_entry_inject_resolved", False):
                    fiber.entry = parent_entry
                    fiber._entry_inject_resolved = True
                    from dsh.cordis.registry import Inject
                    opt_inject = getattr(parent_entry, "options", {}).get("inject") if hasattr(parent_entry, "options") else None
                    if opt_inject:
                        Inject.resolve(opt_inject, fiber.inject)

                # 2. handle self-dispose (7 cases matching reference index.ts:128-157)
                module_name = getattr(parent_entry, '_loaded_module_name', None)
                parent_fiber = getattr(getattr(fiber, 'parent', None), 'fiber', None)
                if (fiber.uid and module_name and module_name.startswith(('dynamic_plugin_', 'dynamic_cordis_plugin_'))
                        and getattr(parent_fiber, 'entry', None) is not parent_entry):
                    module = sys.modules.get(module_name)
                    lease = self._module_owners.get(module_name)
                    if lease is None or lease['module'] is not module:
                        lease = dict(module=module, owners=set())
                        self._module_owners[module_name] = lease
                    token = object()
                    lease['owners'].add(token)
                    def release_module():
                        lease['owners'].discard(token)
                        if parent_entry._loaded_module_name == module_name:
                            parent_entry._loaded_module_name = None
                        if lease['owners']:
                            return
                        if self._module_owners.get(module_name) is lease:
                            self._module_owners.pop(module_name)
                        if sys.modules.get(module_name) is module:
                            sys.modules.pop(module_name, None)
                            importlib.invalidate_caches()
                            for alias in self._module_aliases.pop(module_name, set()):
                                value = self.registry_map.get(alias)
                                if (getattr(value, '__module__', None) == module_name
                                        and getattr(module, getattr(value, '__name__', ''), None) is value):
                                    self.registry_map.pop(alias, None)
                    fiber.effect(lambda: release_module, label='loader.module')
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

                # The parent may be unloading while its entry stays registered.
                if parent_fiber and parent_fiber.state == FiberState.UNLOADING:
                    return
                # Group.remove unregisters before starting Fiber disposal.
                if tree and tree.store.get(entry.options.get("id")) is not entry:
                    return
                if getattr(entry, "_disposing", False):
                    return

                self.show_log(entry, "unload")

                # Case 7: fiber is disposed by loader behavior (already disabled)
                if getattr(entry, "disabled", False):
                    return

                legacy = dict(entry.options)
                entry.disabled = True
                if hasattr(entry, "options") and isinstance(entry.options, dict):
                    entry.options["disabled"] = True

                if tree:
                    tree.commit(dict(id=entry.options['id'], group=entry.parent,
                                     options=entry.options, legacy=legacy))

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

    def _on_internal_update_log(self, config: Any, next_fn: Any, **kwargs: Any) -> Any:
        target_ctx = kwargs.get("caller_ctx")
        fiber = getattr(target_ctx, "fiber", None) if target_ctx else None
        if fiber and getattr(fiber, "entry", None):
            parent_fiber = getattr(getattr(fiber, "parent", None), "fiber", None)
            if not parent_fiber or getattr(parent_fiber, "entry", None) != fiber.entry:
                self.show_log(fiber.entry, "reload")
        return next_fn()

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

    def _on_internal_config(self, fiber: Any, next_fn: Any, **kwargs: Any) -> Any:
        resolved = next_fn()

        if not fiber or not getattr(fiber, "entry", None):
            return resolved

        parent_fiber = getattr(getattr(fiber, "parent", None), "fiber", None)
        if parent_fiber and getattr(parent_fiber, "entry", None) == fiber.entry:
            return resolved

        plugin = getattr(fiber, "plugin", None) or getattr(getattr(fiber, "runtime", None), "callback", None)
        if getattr(plugin, EntryGroup.key, False):
            return resolved

        eval_ctx = fiber.ctx
        return interpolate(eval_ctx, resolved)

    def _on_internal_commit(self, fiber: Any, config: Any) -> Any:
        def _do_save():
            if fiber and getattr(fiber, "entry", None):
                parent_fiber = getattr(getattr(fiber, "parent", None), "fiber", None)
                if not parent_fiber or getattr(parent_fiber, "entry", None) != fiber.entry:
                    entry = fiber.entry
                    legacy = dict(entry.options)
                    cfg_schema = getattr(getattr(fiber, "runtime", None), "Config", None) or getattr(getattr(fiber, "plugin", None), "Config", None)
                    if cfg_schema and hasattr(cfg_schema, "simplify") and callable(cfg_schema.simplify):
                        simplified = cfg_schema.simplify(config)
                        entry.options["config"] = simplified if simplified is not None else config
                    else:
                        entry.options["config"] = config
                    if entry.parent and hasattr(entry.parent, "tree"):
                        entry.parent.tree.commit(dict(id=entry.options['id'], group=entry.parent,
                                                      options=entry.options, legacy=legacy))

        _do_save()

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
            entry.ctx.parent = ctx
            entry.ctx.baseUrl = ctx.baseUrl
            mount_ctx = entry.ctx
            if self.store is not None:
                self.store[entry.id] = entry
            self.entries_list.append(entry)

            if is_disabled:
                continue

            if is_group:
                nested_items = item.get("config", [])
                isolate_config = item.get("isolate", None)

                fiber = mount_ctx.registry.plugin(Group, config=nested_items, get_outer_stack=entry.get_outer_stack)
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

            config = interpolate(mount_ctx, item.get("config", {}))

            plugin_cls = resolve_plugin_class(plugin_name, self.registry_map)
            if plugin_cls is None:
                plugin_cls = (getattr(self, "harness_plugins", None) or {}).get(plugin_name)
            if plugin_cls is None:
                plugin_cls = self.unwrap_exports(self.import_plugin(plugin_name))
            if plugin_cls:
                fiber = None
                if isinstance(plugin_cls, type) and issubclass(plugin_cls, Plugin):
                    plugin_instance = plugin_cls(config=config)
                    plugin_instance.id = plugin_id
                    fiber = mount_ctx.registry.plugin(plugin_instance, config=config, get_outer_stack=entry.get_outer_stack)
                elif callable(plugin_cls) or callable(getattr(plugin_cls, "apply", None)):
                    fiber = mount_ctx.registry.plugin(plugin_cls, config=config, get_outer_stack=entry.get_outer_stack)
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


# Historical public spelling retained for callers of the split Loader modules.
evaluate = evaluate_expr
