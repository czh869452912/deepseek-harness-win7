"""
Schemastery: Runtime schema validation & type specification DSL for Cordis
1:1 matching reference/vendor/schemastery/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.

Language and platform adaptations, all recorded at their call site:

* JavaScript `undefined` has no Python value; the port reads it back as `None`
  and renders it as `null` in serialized output, so a resolver's "no adapted
  value" result and a schema member that resolved to null are one value here.
* `Object.assign` copies a schema's own properties by reference, so `_clone`
  shares containers; a JavaScript `new Function('return ' + source)()` cannot
  rehydrate a Python callback, so `Schema.from_json` keeps the callback source
  and a rehydrated transform fails loud when it is validated.
* JavaScript type names (`Date`, `RegExp`) and `Number.prototype.toString`
  spellings differ from the Python types the port validates (`datetime.date`,
  `re.Pattern`), which shows up in `toString()` and in message operands.
"""

import copy
import datetime
import inspect
import json
import math
import re
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple, Union

from dsh.cordis.utils import (
    _js_own_enumerable_keys,
    _js_reorder_mapping,
    clone,
    deep_equal,
    is_nullable,
    js_to_string,
)

__schemastery_index__ = 0


#: Memoized positional arity of resolvers, callbacks and predicates.  The
#: reference passes a fixed argument list and relies on the engine dropping the
#: arguments a callee does not declare.
_ARITY_CACHE: Dict[Any, int] = {}


def _positional_arity(fn: Callable[..., Any], maximum: int) -> int:
    """
    Count the leading positional parameters `fn` accepts, capped at `maximum`.

    The reference calls every resolver as `resolve(data, schema, options,
    strict)`, every transform callback as `callback(result)` and every `ignore`
    predicate as `ignore(data, schema)`; a JavaScript callee that declares fewer
    parameters ignores the extra arguments.  Python raises `TypeError` for the
    same call, so this port passes exactly the leading arguments the callee
    declares (LEGAL_ADAPTATION).
    """
    try:
        arity = _ARITY_CACHE.get(fn)
    except TypeError:  # an unhashable callee cannot be memoized
        return _count_positional_params(fn, maximum)
    if arity is None:
        arity = _count_positional_params(fn, maximum)
        _ARITY_CACHE[fn] = arity
    return arity


def _count_positional_params(fn: Callable[..., Any], maximum: int) -> int:
    """Count leading positional parameters, treating `*args` as `maximum`."""
    try:
        parameters = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return maximum
    count = 0
    for parameter in parameters:
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            count += 1
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return maximum
    return min(count, maximum)


def _call_with_arity(fn: Callable[..., Any], arguments: Tuple[Any, ...]) -> Any:
    """Call `fn` with the leading `arguments` its signature declares."""
    return fn(*arguments[:_positional_arity(fn, len(arguments))])


def _iso_datetime(value: datetime.datetime) -> str:
    """`Date.prototype.toJSON`: an ISO 8601 UTC timestamp with milliseconds."""
    if value.tzinfo is not None:
        value = value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(value.microsecond // 1000)


def _json_text(data: Any) -> Optional[str]:
    """
    `JSON.stringify` text for one value, or `None` where it yields `undefined`.

    The reference formats union and intersect failures with a
    `JSON.stringify(data)` template literal.  A function or symbol is not
    representable, and the port's non-JSON value types (`re.Pattern`, `set`,
    `bytes`, `Schema`) carry no own enumerable properties, exactly as their
    JavaScript counterparts serialize to `{}`.
    """
    if data is None:
        return "null"
    if isinstance(data, bool):
        return "true" if data else "false"
    if isinstance(data, (int, float)):
        if isinstance(data, float) and (math.isnan(data) or math.isinf(data)):
            return "null"
        return js_to_string(data)
    if isinstance(data, str):
        return json.dumps(data, ensure_ascii=False)
    if callable(data):
        return None
    if isinstance(data, datetime.datetime):
        return json.dumps(_iso_datetime(data), ensure_ascii=False)
    if isinstance(data, datetime.date):
        return json.dumps(data.isoformat(), ensure_ascii=False)
    if isinstance(data, (list, tuple)):
        return "[" + ",".join(_json_text(item) or "null" for item in data) + "]"
    if isinstance(data, dict):
        parts = []
        for key in _js_own_enumerable_keys(data):
            item = _json_text(data[key])
            if item is None:
                continue
            parts.append(json.dumps(key if isinstance(key, str) else js_to_string(key), ensure_ascii=False) + ":" + item)
        return "{" + ",".join(parts) + "}"
    return "{}"


def _json_stringify(data: Any) -> str:
    """`JSON.stringify(data)` as a validation error message fragment."""
    rendered = _json_text(data)
    return "undefined" if rendered is None else rendered


def _merge_missing(result: Dict[Any, Any], data: Any) -> None:
    """`merge(result, data)` from the reference's object and intersect resolvers."""
    if isinstance(data, (list, tuple)):
        for index in range(len(data)):
            if str(index) in result:
                continue
            result[str(index)] = data[index]
        return
    for key in _js_own_enumerable_keys(data):
        if key in result:
            continue
        result[key] = data[key]


def _value_typeof(value: Any) -> str:
    """ECMAScript `typeof` for the values a resolver returns."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if callable(value):
        return "function"
    return "object"


def _read_key(data: Any, key: Any) -> Any:
    """`data[key]`, where a key the container does not have reads as undefined."""
    if isinstance(data, dict):
        return data.get(key)
    if isinstance(data, (list, tuple)) and isinstance(key, int) and not isinstance(key, bool):
        return data[key] if 0 <= key < len(data) else None
    return None


def _write_key(data: Any, key: Any, value: Any) -> None:
    """`data[key] = value` for the container shapes a resolver receives."""
    if isinstance(data, dict):
        data[key] = value
    elif isinstance(data, list) and isinstance(key, int) and not isinstance(key, bool) and 0 <= key < len(data):
        data[key] = value


def _delete_key(data: Any, key: Any) -> None:
    """
    `delete data[key]` for the autofix path.

    A JavaScript array keeps its length after `delete` and reads the removed
    index as `undefined`; a Python list cannot hold a hole, so the port stores
    the port's nullish value at that index (LEGAL_ADAPTATION).
    """
    if isinstance(data, dict):
        data.pop(key, None)
    elif isinstance(data, list) and isinstance(key, int) and not isinstance(key, bool) and 0 <= key < len(data):
        data[key] = None


#: Python callables the reference maps to its `Function` constructor in the
#: `Schema.from()` shorthand table.
_FUNCTION_TYPES = (
    type(lambda: None),
    type(len),
    type(object.__init__),
    type("".upper),
)


def _callback_source(schema: Any) -> Optional[str]:
    """
    Serialized source text of a transform callback.

    The reference serializes a function through `Function.prototype.toString()`
    and rehydrates the text with `new Function('return ' + source)()`.  Python
    keeps source text only for functions defined on disk, so this port stores
    `inspect.getsource()` when available and the callable's name otherwise;
    `Schema.from_json` keeps that text in `callback_source` and validation of a
    rehydrated transform fails loud instead of evaluating the text
    (LEGAL_ADAPTATION, see `Schema.from_json`).
    """
    callback = schema.callback
    if callback is not None:
        if isinstance(callback, str):
            return callback
        source: Optional[str] = None
        try:
            source = inspect.getsource(callback).strip()
        except Exception:
            source = None
        if source:
            return source
        return getattr(callback, "__name__", None) or repr(callback)
    return getattr(schema, "callback_source", None)


def _to_int32(value: Any) -> int:
    """ECMAScript `ToInt32`, used by the bitset resolver's `data & bits[key]`."""
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return 0
    truncated = int(number) if number >= 0 else -int(-number)
    return ((truncated + 2 ** 31) % 2 ** 32) - 2 ** 31


class ValidationError(TypeError):
    """
    Error raised when data fails schema validation.

    Carries either one message with its validation options, matching
    Schemastery's `ValidationError(message, options)`, or the aggregated issue
    list that cordis builds in `resolveConfig`, matching the reference's
    `ValidationError(issues)`.  Both carry the reference's
    `Symbol.for('ValidationError')` marker.
    """

    name = "ValidationError"

    #: Marker matching the reference's `Symbol.for('ValidationError')` prototype
    #: property, shared by schemastery and cordis config validation.
    _kValidationError = True

    def __init__(self, message_or_issues: Any, options: Optional[Dict[str, Any]] = None):
        if isinstance(message_or_issues, list):
            self.issues = message_or_issues
            self.options = options or {}
            lines = []
            for issue in message_or_issues:
                if isinstance(issue, dict):
                    msg = issue.get("message", str(issue))
                    path = issue.get("path")
                else:
                    msg = str(issue)
                    path = None
                if path:
                    path_str = ".".join(str(item) for item in path) if isinstance(path, (list, tuple)) else str(path)
                    lines.append("  - {} (at {})".format(msg, path_str))
                else:
                    lines.append("  - {}".format(msg))
            full_msg = "invalid config:\n" + "\n".join(lines)
            super().__init__(full_msg)
            self.message = full_msg
            self.path = []
            return

        self.options = options or {}
        self.path = self.options.get("path", [])

        prefix = "$"
        for segment in self.path:
            if isinstance(segment, str):
                prefix += "." + segment
            elif isinstance(segment, int) and not isinstance(segment, bool):
                prefix += "[" + str(segment) + "]"
            elif segment is None or isinstance(segment, bool):
                continue
            else:
                prefix += "[" + str(segment) + "]"

        if prefix.startswith("."):
            prefix = prefix[1:]

        msg_str = str(message_or_issues)
        full_msg = msg_str if prefix == "$" else prefix + " " + msg_str
        super().__init__(full_msg)
        self.message = full_msg

    @staticmethod
    def is_(error: Any) -> bool:
        """Return whether `error` carries the ValidationError marker matching TS ValidationError.is."""
        return bool(getattr(error, "_kValidationError", False))


# `deepEqual`, `isNullable` and `clone` are Cosmokit helpers shared with the
# framework layer; the port re-exports them under the names Schemastery's
# resolvers and `simplify()` call.
class Schema:
    """
    Schemastery Schema definition matching reference/vendor/schemastery/src/index.ts.
    Provides fluent builder methods, validation, simplification, i18n, and JSON serialization.
    """

    resolvers: Dict[str, Callable[..., Any]] = {}

    def __init__(self, options: Optional[Dict[str, Any]] = None):
        global __schemastery_index__
        self.uid: int = __schemastery_index__
        __schemastery_index__ += 1

        self.type: str = "any"
        self.meta: Dict[str, Any] = {}
        self.value: Any = None
        self.inner: Optional["Schema"] = None
        self.s_key: Optional["Schema"] = None
        self.list: Optional[List["Schema"]] = None
        self.dict: Optional[Dict[str, "Schema"]] = None
        self.bits: Optional[Dict[str, int]] = None
        self.callback: Optional[Callable[..., Any]] = None
        self.callback_source: Optional[str] = None
        self.constructor: Optional[Any] = None
        self.builder: Optional[Callable[[], "Schema"]] = None
        self.preserve: bool = False

        if options:
            opts = dict(options)
            opts.pop("uid", None)
            cb = opts.get("callback")
            if cb is not None and not callable(cb):
                opts.pop("callback")
                self.callback_source = str(cb)
            for k, v in opts.items():
                setattr(self, k, v)
        if not isinstance(self.meta, dict):
            self.meta = {}

    def __call__(self, data: Any = None, options: Optional[Dict[str, Any]] = None) -> Any:
        return Schema.resolve(data, self, options or {})[0]

    # --- Standard Schema V1 compatibility (@standard-schema/spec) ---
    @property
    def standard(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "vendor": "schemastery",
            "validate": self.validate,
        }

    def __getitem__(self, item: str) -> Any:
        if item in ("~standard", "standard"):
            return self.standard
        raise KeyError(item)

    def validate(self, value: Any) -> Dict[str, Any]:
        """
        Standard Schema V1 `validate` matching the reference's `~standard`.

        Returns `{ value }` on success, or `{ issues: [{ message, path }] }`
        where `message` is the full `ValidationError` message (it already opens
        with the `$....` path prefix) and `path` is the error's path array, as
        the reference's `~standard.validate` reports.
        """
        try:
            res = Schema.resolve(value, self, {})[0]
            return {"value": res}
        except ValidationError as err:
            path = err.options.get("path") if isinstance(getattr(err, "options", None), dict) else None
            return {"issues": [{"message": str(err), "path": path}]}

    # --- Fluent modifier methods (return a clone with updated meta) ---
    def _clone(self) -> "Schema":
        """
        Copy this schema matching the reference's `Schema(this)` spread.

        `Object.assign` copies own enumerable properties by reference, so a
        clone shares `meta`, `inner`, `sKey`, `list`, `dict`, `bits` and
        `preserve` with its source until a builder method replaces one; `set()`
        and `push()` therefore write into the container the source also holds.
        """
        s = Schema()
        s.type = self.type
        s.meta = self.meta
        s.value = self.value
        s.inner = self.inner
        s.s_key = self.s_key
        s.list = self.list
        s.dict = self.dict
        s.bits = self.bits
        s.callback = self.callback
        s.callback_source = getattr(self, "callback_source", None)
        s.constructor = self.constructor
        s.builder = self.builder
        s.preserve = self.preserve
        if getattr(self, "_dynamic", False):
            s._dynamic = True
        return s

    def _with_meta(self, key: str, value: Any) -> "Schema":
        """Clone with `key` replaced in a fresh meta object, as the reference does."""
        s = self._clone()
        s.meta = {**s.meta, key: value}
        return s

    def required(self, value: bool = True) -> "Schema":
        return self._with_meta("required", value)

    def optional(self) -> "Schema":
        return self._with_meta("required", False)

    def nullable(self) -> "Schema":
        return self._with_meta("loose", True)

    def hidden(self, value: bool = True) -> "Schema":
        return self._with_meta("hidden", value)

    def loose(self, value: bool = True) -> "Schema":
        return self._with_meta("loose", value)

    def disabled(self, value: bool = True) -> "Schema":
        return self._with_meta("disabled", value)

    def collapse(self, value: bool = True) -> "Schema":
        return self._with_meta("collapse", value)

    def role(self, text: str, extra: Any = None) -> "Schema":
        s = self._clone()
        new_meta = {**s.meta, "role": text}
        if extra is not None:
            new_meta["extra"] = extra
        s.meta = new_meta
        return s

    def link(self, url: str) -> "Schema":
        return self._with_meta("link", url)

    def default(self, val: Any) -> "Schema":
        return self._with_meta("default", val)

    def comment(self, text: str) -> "Schema":
        return self._with_meta("comment", text)

    def description(self, text: str) -> "Schema":
        return self._with_meta("description", text)

    def deprecated(self) -> "Schema":
        s = self._clone()
        badges = list(s.meta.get("badges", []))
        badges.append({"text": "deprecated", "type": "danger"})
        s.meta = {**s.meta, "badges": badges}
        return s

    def experimental(self) -> "Schema":
        s = self._clone()
        badges = list(s.meta.get("badges", []))
        badges.append({"text": "experimental", "type": "warning"})
        s.meta = {**s.meta, "badges": badges}
        return s

    def badges(self, badge_list: List[Dict[str, str]]) -> "Schema":
        return self._with_meta("badges", list(badge_list))

    def pattern(self, regex: Union[str, re.Pattern]) -> "Schema":
        s = self._clone()
        if isinstance(regex, str):
            pattern = {"source": regex, "flags": ""}
        else:
            flags_str = ""
            if regex.flags & re.IGNORECASE:
                flags_str += "i"
            if regex.flags & re.MULTILINE:
                flags_str += "m"
            if regex.flags & re.DOTALL:
                flags_str += "s"
            pattern = {"source": regex.pattern, "flags": flags_str}
        s.meta = {**s.meta, "pattern": pattern}
        return s

    def max(self, value: Union[int, float]) -> "Schema":
        return self._with_meta("max", value)

    def min(self, value: Union[int, float]) -> "Schema":
        return self._with_meta("min", value)

    def step(self, value: Union[int, float]) -> "Schema":
        return self._with_meta("step", value)

    def extra(self, key: str, value: Any) -> "Schema":
        return self._with_meta(key, value)

    def set(self, key: str, value: "Schema") -> "Schema":
        if self.dict is None:
            raise TypeError(f"Cannot set property '{key}' on schema without dict container")
        self.dict[key] = value
        return self

    def push(self, value: "Schema") -> "Schema":
        if self.list is None:
            raise TypeError("Cannot push item to schema without list container")
        self.list.append(value)
        return self

    def i18n(self, messages: Dict[str, Any]) -> "Schema":
        """Attach localized descriptions matching TS Schema.prototype.i18n()."""
        s = self._clone()
        desc = s.meta.get("description")
        desc_dict: Dict[str, str] = {"": desc} if isinstance(desc, str) else dict(desc or {})
        for locale, val in [(key, messages[key]) for key in _js_own_enumerable_keys(messages)]:
            if isinstance(val, dict):
                d = val.get("$description") or val.get("$desc") or val.get("")
                if d:
                    desc_dict[locale] = d
            elif isinstance(val, str):
                desc_dict[locale] = val
        if desc_dict:
            s.meta = {**s.meta, "description": desc_dict}

        if s.dict:
            new_dict = {}
            for k, inner in [(key, s.dict[key]) for key in _js_own_enumerable_keys(s.dict)]:
                sub_msg = {}
                for loc, m in [(key, messages[key]) for key in _js_own_enumerable_keys(messages)]:
                    if isinstance(m, dict):
                        inner_dict = m.get("$value") or m.get("$inner") or m
                        if isinstance(inner_dict, dict) and k in inner_dict:
                            sub_msg[loc] = inner_dict[k]
                    elif isinstance(m, str):
                        sub_msg[loc] = m
                new_dict[k] = inner.i18n(sub_msg)
            s.dict = new_dict

        if s.list:
            new_list = []
            for idx, inner in enumerate(s.list):
                sub_msg = {}
                for loc, m in [(key, messages[key]) for key in _js_own_enumerable_keys(messages)]:
                    if isinstance(m, dict):
                        inner_list = m.get("$value") or m.get("$inner") or m
                        if isinstance(inner_list, (list, tuple)) and idx < len(inner_list):
                            sub_msg[loc] = inner_list[idx]
                        elif isinstance(inner_list, dict):
                            sub_msg[loc] = {k: v for k, v in inner_list.items() if not k.startswith("$")}
                    elif isinstance(m, str):
                        sub_msg[loc] = m
                new_list.append(inner.i18n(sub_msg))
            s.list = new_list

        if s.inner:
            sub_msg = {}
            for loc, m in [(key, messages[key]) for key in _js_own_enumerable_keys(messages)]:
                if isinstance(m, dict):
                    inner_val = m.get("$value") or m.get("$inner") or {k: v for k, v in m.items() if not k.startswith("$")}
                    sub_msg[loc] = inner_val
                elif isinstance(m, str):
                    sub_msg[loc] = m
            s.inner = s.inner.i18n(sub_msg)

        if s.s_key:
            sub_msg = {}
            for loc, m in messages.items():
                if isinstance(m, dict) and "$key" in m:
                    sub_msg[loc] = m["$key"]
            s.s_key = s.s_key.i18n(sub_msg)

        return s

    def simplify(self, value: Any = None) -> Any:
        """Remove values equal to schema defaults matching TS Schema.simplify()."""
        if deep_equal(value, self.meta.get("default"), self.type == "dict"):
            return None
        if is_nullable(value):
            return value

        if self.type in ("object", "dict"):
            if not isinstance(value, dict):
                return value
            res: Dict[str, Any] = {}
            for key in _js_own_enumerable_keys(value):
                schema = (self.dict or {}).get(key) if self.type == "object" else self.inner
                # `schema?.simplify(value[key])` keeps `undefined` for a member
                # the schema does not declare, which the nullish test below then
                # drops for an object and keeps for a dict.
                item = schema.simplify(value[key]) if schema is not None else None
                if self.type == "dict" or not is_nullable(item):
                    res[key] = item
            if deep_equal(res, self.meta.get("default"), self.type == "dict"):
                return None
            return res
        elif self.type in ("array", "tuple"):
            if not isinstance(value, (list, tuple)):
                return value
            arr: List[Any] = []
            for index, item in enumerate(value):
                schema = self.inner if self.type == "array" else (self.list[index] if self.list and index < len(self.list) else None)
                arr.append(schema.simplify(item) if schema else item)
            return arr
        elif self.type == "intersect" and self.list:
            res = {}
            for item in self.list:
                s_res = item.simplify(value)
                if isinstance(s_res, dict):
                    res.update(s_res)
            return res
        elif self.type == "union" and self.list:
            for schema in self.list:
                try:
                    Schema.resolve(value, schema, {})
                    return schema.simplify(value)
                except Exception:
                    pass
        return value

    def toJSON(self, refs_collector: Optional[Dict[int, Dict[str, Any]]] = None) -> Union[int, Dict[str, Any]]:
        """
        Serialize schema definition with flat reference table matching TS Schema.prototype.toJSON().
        Returns { "uid": self.uid, "refs": { ... } } at root level, or node uid when called recursively.
        """
        is_root = refs_collector is None
        if self.type == "lazy" and self.inner is None and callable(getattr(self, "builder", None)):
            built = self.builder()
            built.meta = {**self.meta, **built.meta}
            self.inner = built

        if is_root:
            refs: Dict[int, Dict[str, Any]] = {}
        else:
            refs = refs_collector

        if self.uid in refs:
            return self.uid

        node: Dict[str, Any] = {
            "type": self.type,
            "meta": dict(self.meta),
        }
        refs[self.uid] = node

        if self.value is not None:
            node["value"] = self.value
        if self.inner:
            node["inner"] = self.inner.toJSON(refs)
        if self.s_key:
            node["sKey"] = self.s_key.toJSON(refs)
        if self.list:
            node["list"] = [s.toJSON(refs) for s in self.list]
        if self.dict:
            node["dict"] = {k: v.toJSON(refs) for k, v in self.dict.items()}
        if self.bits:
            node["bits"] = dict(self.bits)
        if self.preserve:
            node["preserve"] = self.preserve
        if self.constructor is not None:
            if isinstance(self.constructor, type):
                node["constructor"] = self.constructor.__name__
            else:
                node["constructor"] = str(self.constructor)
        source = _callback_source(self)
        if source is not None:
            node["callback"] = source

        if is_root:
            return {"uid": self.uid, "refs": refs}
        return self.uid

    def to_json(self) -> Dict[str, Any]:
        """Serialize schema definition matching TS toJSON()."""
        if self.type == "lazy" and self.inner is None and callable(getattr(self, "builder", None)):
            built = self.builder()
            built.meta = {**self.meta, **built.meta}
            self.inner = built

        res: Dict[str, Any] = {
            "uid": self.uid,
            "type": self.type,
            "meta": self.meta,
        }
        if self.value is not None:
            res["value"] = self.value
        if self.inner:
            res["inner"] = self.inner.to_json()
        if self.s_key:
            res["sKey"] = self.s_key.to_json()
        if self.list:
            res["list"] = [s.to_json() for s in self.list]
        if self.dict:
            res["dict"] = {k: v.to_json() for k, v in self.dict.items()}
        if self.bits:
            res["bits"] = self.bits
        if self.preserve:
            res["preserve"] = self.preserve
        if self.constructor is not None:
            if isinstance(self.constructor, type):
                res["constructor"] = self.constructor.__name__
            else:
                res["constructor"] = str(self.constructor)
        source = _callback_source(self)
        if source is not None:
            res["callback"] = source
        return res

    def to_json_schema(self) -> Dict[str, Any]:
        """Convert Schemastery Schema to standard JSON Schema Draft-07 matching TS Schemastery."""
        json_schema: Dict[str, Any] = {}

        if self.type == "string":
            json_schema["type"] = "string"
            if self.meta.get("pattern"):
                pat = self.meta["pattern"]
                json_schema["pattern"] = pat.get("source", pat) if isinstance(pat, dict) else str(pat)
        elif self.type == "number":
            json_schema["type"] = "number"
            if "min" in self.meta:
                json_schema["minimum"] = self.meta["min"]
            if "max" in self.meta:
                json_schema["maximum"] = self.meta["max"]
            if "step" in self.meta:
                json_schema["multipleOf"] = self.meta["step"]
        elif self.type == "boolean":
            json_schema["type"] = "boolean"
        elif self.type == "const":
            json_schema["const"] = self.value
        elif self.type == "array":
            json_schema["type"] = "array"
            if self.inner:
                json_schema["items"] = self.inner.to_json_schema()
            if "min" in self.meta:
                json_schema["minItems"] = self.meta["min"]
            if "max" in self.meta:
                json_schema["maxItems"] = self.meta["max"]
        elif self.type == "dict":
            json_schema["type"] = "object"
            if self.inner:
                json_schema["additionalProperties"] = self.inner.to_json_schema()
        elif self.type == "object":
            json_schema["type"] = "object"
            props: Dict[str, Any] = {}
            required: List[str] = []
            if self.dict:
                for k, s in self.dict.items():
                    props[k] = s.to_json_schema()
                    if s.meta.get("required"):
                        required.append(k)
            json_schema["properties"] = props
            if required:
                json_schema["required"] = required
        elif self.type == "tuple":
            json_schema["type"] = "array"
            if self.list:
                json_schema["items"] = [s.to_json_schema() for s in self.list]
                json_schema["minItems"] = len(self.list)
                json_schema["maxItems"] = len(self.list)
        elif self.type == "union":
            if self.list:
                json_schema["anyOf"] = [s.to_json_schema() for s in self.list]
        elif self.type == "intersect":
            if self.list:
                json_schema["allOf"] = [s.to_json_schema() for s in self.list]
        elif self.type == "bitset":
            json_schema["type"] = "integer"
        elif self.type == "any":
            pass
        elif self.type == "never":
            json_schema["not"] = {}
        elif self.type == "lazy" and self.builder:
            built = self.builder()
            return built.to_json_schema()
        elif self.type == "transform" and self.inner:
            return self.inner.to_json_schema()

        if "description" in self.meta:
            desc = self.meta["description"]
            json_schema["description"] = desc.get("zh", str(desc)) if isinstance(desc, dict) else str(desc)
        if "default" in self.meta and self.meta["default"] is not None:
            json_schema["default"] = self.meta["default"]

        return json_schema

    def to_string(self, inline: bool = False) -> str:
        """
        Format this schema as the reference's `toString()` type string.

        LEGAL_ADAPTATION: the reference's `const` formatter returns the raw
        constant (a number or an object) rather than a string, and its `is`
        formatter returns JavaScript constructor names; this port always returns
        the string form of the same value under the port's type names.
        """
        if self.type == "string":
            return "string"
        elif self.type == "number":
            return "number"
        elif self.type == "boolean":
            return "boolean"
        elif self.type == "any":
            return "any"
        elif self.type == "never":
            return "never"
        elif self.type == "bitset":
            return "bitset"
        elif self.type == "function":
            return "function"
        elif self.type == "const":
            if isinstance(self.value, str):
                return json.dumps(self.value, ensure_ascii=False)
            return js_to_string(self.value)
        elif self.type == "is":
            if isinstance(self.constructor, type):
                return self.constructor.__name__
            if isinstance(self.constructor, str):
                return self.constructor
            return js_to_string(self.constructor)
        elif self.type == "array":
            return "{}[]".format(self.inner.to_string(True) if self.inner else "any")
        elif self.type == "dict":
            inner = self.inner.to_string() if self.inner else "any"
            s_key = self.s_key.to_string() if self.s_key else "string"
            return "{{ [key: {}]: {} }}".format(s_key, inner)
        elif self.type == "tuple":
            items = [schema.to_string() for schema in (self.list or [])]
            return "[{}]".format(", ".join(items))
        elif self.type == "object":
            if not self.dict:
                return "{}"
            members = []
            for key in _js_own_enumerable_keys(self.dict):
                inner = self.dict[key]
                members.append("{}{}: {}".format(key, "" if inner.meta.get("required") else "?", inner.to_string()))
            return "{{ {} }}".format(", ".join(members))
        elif self.type == "union":
            result = " | ".join(schema.to_string() for schema in (self.list or []))
            return "({})".format(result) if inline and len(self.list or []) > 1 else result
        elif self.type == "intersect":
            return " & ".join(schema.to_string(True) for schema in (self.list or []))
        elif self.type == "transform":
            return self.inner.to_string(inline) if self.inner else "any"
        return "Schema<{}>".format(self.type)

    def __str__(self) -> str:
        return self.to_string()

    def __repr__(self) -> str:
        return f"Schema<{self.type}>"

    @classmethod
    def from_json(cls, payload: Dict[str, Any]) -> "Schema":
        """
        Deserialize Schema tree from flat refs dictionary matching TS Schema(options.refs).

        Permitted ADAPT deviation:
        In TypeScript Schemastery, deserialization may evaluate string callback functions via
        `new Function(...)`. In Python 3.8, arbitrary serialized code string evaluation is intentionally
        omitted for safety and deterministic runtime semantics. `callback` is kept as None (preserving
        `callback_source`), and `_resolve_transform` raises a 1:1 fail-loud TypeError when validation
        is attempted on an uncallable transform callback.
        """
        if not isinstance(payload, dict):
            return cls.any()
        if "refs" in payload and isinstance(payload["refs"], dict):
            refs_dict = payload["refs"]
            schema_map: Dict[int, "Schema"] = {}
            for uid_str, raw_node in refs_dict.items():
                try:
                    uid_int = int(uid_str)
                except (ValueError, TypeError):
                    continue
                s = cls(raw_node)
                s.uid = uid_int
                schema_map[uid_int] = s

            def _get_ref(target_uid: Any) -> Any:
                if target_uid is None:
                    return None
                try:
                    return schema_map.get(int(target_uid))
                except (ValueError, TypeError):
                    return None

            for uid_int, s in schema_map.items():
                raw_node = refs_dict.get(str(uid_int), refs_dict.get(uid_int))
                if raw_node is None:
                    continue
                if "inner" in raw_node:
                    s.inner = _get_ref(raw_node["inner"])
                if "sKey" in raw_node or "s_key" in raw_node:
                    s.s_key = _get_ref(raw_node.get("sKey") if "sKey" in raw_node else raw_node.get("s_key"))
                if "list" in raw_node and isinstance(raw_node["list"], list):
                    s.list = [_get_ref(item) for item in raw_node["list"]]
                if "dict" in raw_node and isinstance(raw_node["dict"], dict):
                    s.dict = {k: _get_ref(v) for k, v in raw_node["dict"].items()}

            target_uid = payload.get("uid")
            if target_uid is not None:
                try:
                    target_int = int(target_uid)
                    if target_int in schema_map:
                        return schema_map[target_int]
                except (ValueError, TypeError):
                    pass
            return cls.any()
        return cls(payload)

    fromJSON = from_json

    # --- Factory Classmethods matching TS Schemastery.Static ---
    @classmethod
    def extend(cls, type_name: str, resolve_fn: Callable[..., Any]) -> None:
        cls.resolvers[type_name] = resolve_fn

    @classmethod
    def any(cls) -> "Schema":
        return cls({"type": "any"})

    @classmethod
    def never(cls) -> "Schema":
        return cls({"type": "never"})

    @classmethod
    def const_(cls, value: Any) -> "Schema":
        return cls({"type": "const", "value": value})

    @classmethod
    def string(cls) -> "Schema":
        return cls({"type": "string"})

    @classmethod
    def number(cls) -> "Schema":
        return cls({"type": "number"})

    @classmethod
    def natural(cls) -> "Schema":
        return cls.number().step(1).min(0)

    @classmethod
    def percent(cls) -> "Schema":
        return cls.number().step(0.01).min(0).max(1).role("slider")

    @classmethod
    def boolean(cls) -> "Schema":
        return cls({"type": "boolean"})

    @classmethod
    def date(cls) -> "Schema":
        def _parse_date(val: Any, opt: Any) -> datetime.datetime:
            if isinstance(val, (datetime.datetime, datetime.date)):
                return val
            if isinstance(val, str):
                iso_str = val
                if iso_str.endswith("Z"):
                    iso_str = iso_str[:-1] + "+00:00"
                try:
                    return datetime.datetime.fromisoformat(iso_str)
                except Exception:
                    raise ValidationError(f'invalid date "{val}"', opt)
            raise ValidationError(f"expected Date or date string but got {val}", opt)

        return cls.union([
            cls.is_(datetime.date),
            cls.transform(cls.string().role("datetime"), _parse_date, preserve=True)
        ])

    @classmethod
    def reg_exp(cls, flag: str = "") -> "Schema":
        def _parse_regex(val: Any, opt: Any) -> re.Pattern:
            if isinstance(val, re.Pattern):
                return val
            if isinstance(val, str):
                try:
                    re_flags = 0
                    if "i" in flag: re_flags |= re.IGNORECASE
                    if "m" in flag: re_flags |= re.MULTILINE
                    if "s" in flag: re_flags |= re.DOTALL
                    return re.compile(val, re_flags)
                except Exception as e:
                    raise ValidationError(str(e), opt)
            raise ValidationError(f"expected RegExp or regex string but got {val}", opt)

        return cls.union([
            cls.is_(re.Pattern),
            cls.transform(cls.string().role("regexp", {"flag": flag}), _parse_regex, preserve=True)
        ])

    @classmethod
    def array_buffer(cls, encoding: Optional[str] = None) -> "Schema":
        def _parse_str(val: Any, opt: Any) -> bytes:
            if isinstance(val, (bytes, bytearray, memoryview)):
                return bytes(val)
            if isinstance(val, str) and encoding:
                try:
                    if encoding == "base64":
                        import base64
                        return base64.b64decode(val)
                    elif encoding == "hex":
                        import binascii
                        return binascii.unhexlify(val)
                except Exception as e:
                    raise ValidationError(f"invalid binary encoding: {e}", opt)
            raise ValidationError(f"expected binary but got {val}", opt)

        branches = [
            cls.is_(bytes),
            cls.is_(bytearray),
            cls.is_(memoryview),
        ]
        if encoding:
            branches.append(cls.transform(cls.string(), _parse_str, preserve=True))
        return cls.union(branches)

    @classmethod
    def bitset(cls, bits: Dict[str, int]) -> "Schema":
        clean_bits = {k: v for k, v in bits.items() if isinstance(v, int) and not isinstance(v, bool)}
        s = cls({"type": "bitset", "bits": clean_bits})
        s.meta["default"] = 0
        return s

    @classmethod
    def function(cls) -> "Schema":
        return cls({"type": "function"})

    @classmethod
    def is_(cls, constructor: Any) -> "Schema":
        return cls({"type": "is", "constructor": constructor})

    @classmethod
    def array(cls, inner: Any) -> "Schema":
        s = cls({"type": "array", "inner": cls.from_(inner)})
        s.meta["default"] = []
        return s

    @classmethod
    def dict(cls, inner: Any, s_key: Any = None) -> "Schema":
        s = cls({
            "type": "dict",
            "inner": cls.from_(inner),
            "s_key": cls.from_(s_key) if s_key is not None else cls.string(),
        })
        s.meta["default"] = {}
        return s

    @classmethod
    def tuple(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        s = cls({"type": "tuple", "list": [cls.from_(x) for x in list_types]})
        s.meta["default"] = []
        return s

    @classmethod
    def object(cls, dict_types: Dict[str, Any]) -> "Schema":
        s = cls({"type": "object", "dict": {k: cls.from_(v) for k, v in dict_types.items()}})
        s.meta["default"] = {}
        return s

    @classmethod
    def union(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        return cls({"type": "union", "list": [cls.from_(x) for x in list_types]})

    @classmethod
    def intersect(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        return cls({"type": "intersect", "list": [cls.from_(x) for x in list_types]})

    @classmethod
    def transform(cls, inner: Any, callback: Callable[..., Any], preserve: bool = False) -> "Schema":
        return cls({"type": "transform", "inner": cls.from_(inner), "callback": callback, "preserve": preserve})

    @classmethod
    def lazy(cls, builder: Callable[[], "Schema"]) -> "Schema":
        return cls({"type": "lazy", "builder": builder})

    @classmethod
    def dynamic(cls, builder: Callable[..., "Schema"]) -> "Schema":
        """Dynamic schema factory matching TS Schemastery.dynamic."""
        return cls({"type": "lazy", "builder": builder, "_dynamic": True})

    @classmethod
    def computed(cls, callback: Callable[..., Any]) -> "Schema":
        """Computed schema property based on context or sibling values."""
        def _resolve_computed(data: Any, opt: Any) -> Any:
            return _call_with_arity(callback, (opt.get("root", data),))
        return cls.transform(cls.any(), _resolve_computed)


    @classmethod
    def from_(cls, source: Any = None) -> "Schema":
        """
        Infer a schema from a primitive value, constructor, or existing schema.

        Matches the reference's `Schema.from()` shorthand table: a nullish
        source is `any()`, a primitive is a required `const`, the framework's
        function constructor maps to `function()`, and every other constructor
        maps to `is()`.
        """
        if is_nullable(source):
            return cls.any()
        if isinstance(source, Schema):
            return source
        if isinstance(source, (str, int, float, bool)):
            return cls.const_(source).required()
        if source in _FUNCTION_TYPES:
            return cls.function().required()
        if source is str:
            return cls.string().required()
        if source in (int, float):
            return cls.number().required()
        if source is bool:
            return cls.boolean().required()
        if callable(source):
            return cls.is_(source).required()
        if isinstance(source, type):
            return cls.is_(source).required()
        raise TypeError("cannot infer schema from " + js_to_string(source))

    # 1:1 camelCase and standard aliases matching Schemastery
    const = const_
    is_type = is_
    from_type = from_
    regExp = reg_exp
    arrayBuffer = array_buffer
    toString = to_string

    @classmethod
    def resolve(cls, data: Any, schema: "Schema", options: Optional[Dict[str, Any]] = None, strict: bool = False) -> Tuple[Any, Any]:
        """
        Validate `data` against one schema node.

        Returns `(value, adapted)`, where `adapted` is the nullish equivalent of
        the reference's `undefined` "no adapted value" result for the methods
        that write a normalized value back into the validated container.
        """
        opt = options or {}
        if not schema:
            return data, None

        ignore_fn = opt.get("ignore")
        if callable(ignore_fn) and _call_with_arity(ignore_fn, (data, schema)):
            return data, None

        if is_nullable(data) and schema.type != "lazy":
            if schema.meta.get("required"):
                raise ValidationError("missing required value", opt)
            fallback = schema.meta.get("default")
            current = schema
            while current is not None and getattr(current, "type", None) == "intersect" and is_nullable(fallback):
                current = current.list[0] if getattr(current, "list", None) else None
                fallback = current.meta.get("default") if current is not None else None
            if is_nullable(fallback):
                return data, None
            data = clone(fallback)

        callback = cls.resolvers.get(schema.type)
        if not callback:
            raise ValidationError('unsupported type "{}"'.format(schema.type), opt)

        try:
            result = _call_with_arity(callback, (data, schema, opt, strict))
        except Exception as error:
            if not schema.meta.get("loose"):
                raise error
            return schema.meta.get("default"), None
        if isinstance(result, (list, tuple)):
            return result[0], result[1] if len(result) > 1 else None
        return result, None


# --- Built-in Type Resolvers matching TS schemastery resolvers ---

def _check_range(data: Union[int, float], meta: Dict[str, Any], description: str, opt: Dict[str, Any], skip_min: bool = False) -> None:
    """Range check shared by the string, number and array resolvers."""
    max_val = meta.get("max", math.inf)
    min_val = meta.get("min", -math.inf)
    if data > max_val:
        raise ValidationError("expected {} <= {} but got {}".format(description, js_to_string(max_val), js_to_string(data)), opt)
    if not skip_min and data < min_val:
        raise ValidationError("expected {} >= {} but got {}".format(description, js_to_string(min_val), js_to_string(data)), opt)


def _decimal_shift(data: Union[int, float], digits: int) -> float:
    """`decimalShift` from the reference's number resolver."""
    source = js_to_string(data)
    if "e" in source:
        return data * (10 ** digits)
    index = source.find(".")
    if index == -1:
        return data * (10 ** digits)
    fraction = source[index + 1:]
    integer = source[:index]
    if len(fraction) <= digits:
        return float(integer + fraction.ljust(digits, "0"))
    return float(integer + fraction[:digits] + "." + fraction[digits:])


def _is_multiple_of(data: Union[int, float], minimum: Union[int, float], step: Union[int, float]) -> bool:
    """`isMultipleOf` from the reference's number resolver."""
    step = abs(step)
    source = js_to_string(step)
    if not re.match(r"^[0-9]+\.[0-9]+$", source):
        # ECMAScript `%` truncates toward zero, unlike Python's `%`.
        return math.fmod(data - minimum, step) == 0
    digits = len(source[source.find(".") + 1:])
    return math.fmod(_decimal_shift(data, digits) - _decimal_shift(minimum, digits), _decimal_shift(step, digits)) == 0


def _resolve_lazy(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    """
    `lazy` resolver: build the deferred schema once and merge this node's meta
    into it before validating, exactly as the reference does.

    `Schema.dynamic` is a port-only factory that rebuilds its schema on every
    resolve, so a deferred builder that carries `_dynamic` is never memoized.
    """
    if getattr(schema, "_dynamic", False) and callable(getattr(schema, "builder", None)):
        built = schema.builder()
        built.meta = {**schema.meta, **built.meta}
        return Schema.resolve(data, built, opt, strict)
    if not isinstance(schema.inner, Schema):
        built = schema.builder() if callable(getattr(schema, "builder", None)) else Schema.any()
        built.meta = {**schema.meta, **built.meta}
        schema.inner = built
    return Schema.resolve(data, schema.inner, opt, strict)


def _resolve_any(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    return data, None


def _resolve_never(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    raise ValidationError("expected nullable but got " + js_to_string(data), opt)


def _resolve_const(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if deep_equal(data, schema.value):
        return schema.value, None
    raise ValidationError("expected {} but got {}".format(js_to_string(schema.value), js_to_string(data)), opt)


def _resolve_string(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, str):
        raise ValidationError("expected string but got " + js_to_string(data), opt)
    pattern = schema.meta.get("pattern")
    if pattern:
        source = pattern.get("source") or ""
        flags = pattern.get("flags") or ""
        re_flags = 0
        if "i" in flags:
            re_flags |= re.IGNORECASE
        if "m" in flags:
            re_flags |= re.MULTILINE
        if "s" in flags:
            re_flags |= re.DOTALL
        if not re.search(source, data, flags=re_flags):
            raise ValidationError("expect string to match regexp /{}/{}".format(source, flags), opt)
    _check_range(len(data), schema.meta, "string length", opt)
    return data, None


def _resolve_number(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, (int, float)) or isinstance(data, bool):
        raise ValidationError("expected number but got " + js_to_string(data), opt)
    _check_range(data, schema.meta, "number", opt)
    step = schema.meta.get("step")
    if step:
        minimum = schema.meta.get("min")
        if minimum is None:
            minimum = 0
        if not _is_multiple_of(data, minimum, step):
            raise ValidationError("expected number multiple of {} but got {}".format(js_to_string(step), js_to_string(data)), opt)
    return data, None


def _resolve_boolean(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if isinstance(data, bool):
        return data, None
    raise ValidationError("expected boolean but got " + js_to_string(data), opt)


def _resolve_bitset(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    bits = schema.bits or {}
    value = 0
    keys: List[Any] = []
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        value = data
        numeric = _to_int32(data)
        for key in _js_own_enumerable_keys(bits):
            if numeric & bits[key]:
                keys.append(key)
    elif isinstance(data, (list, tuple)):
        keys = list(data)
        for key in keys:
            if not isinstance(key, str):
                raise ValidationError("expected string but got " + js_to_string(key), opt)
            if key in bits:
                value |= bits[key]
    else:
        raise ValidationError("expected number or array but got " + js_to_string(data), opt)
    if value == schema.meta.get("default"):
        return value, None
    return value, keys


def _resolve_function(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if callable(data):
        return data, None
    raise ValidationError("expected function but got " + js_to_string(data), opt)


def _resolve_is(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    constructor = schema.constructor
    if isinstance(constructor, type):
        if isinstance(data, constructor):
            return data, None
        raise ValidationError("expected {} but got {}".format(constructor.__name__, js_to_string(data)), opt)
    if callable(constructor):
        # The reference's `data instanceof constructor` walks the data's
        # prototype chain; a Python class chain can only contain the callable
        # itself, so a non-class callable matches nothing.
        for base in type(data).__mro__:
            if base is constructor:
                return data, None
        raise ValidationError("expected {} but got {}".format(getattr(constructor, "__name__", js_to_string(constructor)), js_to_string(data)), opt)
    if is_nullable(data):
        raise ValidationError("expected {} but got {}".format(js_to_string(constructor), js_to_string(data)), opt)
    for base in type(data).__mro__:
        if base.__name__ == constructor:
            return data, None
    raise ValidationError("expected {} but got {}".format(js_to_string(constructor), js_to_string(data)), opt)


def _property(data: Any, key: Any, schema: Schema, opt: Dict[str, Any]) -> Any:
    """Validate one container member, writing an adapted value back to `data`."""
    sub_opt = {**opt, "path": list(opt.get("path") or []) + [key]}
    try:
        res, adapted = Schema.resolve(_read_key(data, key), schema, sub_opt)
        if adapted is not None:
            _write_key(data, key, adapted)
        return res
    except Exception as error:
        if not opt.get("autofix"):
            raise error
        _delete_key(data, key)
        return schema.meta.get("default")


def _resolve_array(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, (list, tuple)):
        raise ValidationError("expected array but got " + js_to_string(data), opt)
    inner = schema.inner if isinstance(schema.inner, Schema) else Schema.any()
    _check_range(len(data), schema.meta, "array length", opt, skip_min=not is_nullable(inner.meta.get("default")))
    return [_property(data, index, inner, opt) for index in range(len(data))], None


def _resolve_dict(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, dict):
        raise ValidationError("expected object but got " + js_to_string(data), opt)
    inner = schema.inner if isinstance(schema.inner, Schema) else Schema.any()
    s_key = schema.s_key
    result: Dict[Any, Any] = {}
    for key in _js_own_enumerable_keys(data):
        try:
            r_key = Schema.resolve(key, s_key, opt)[0] if isinstance(s_key, Schema) else key
        except Exception as error:
            if strict:
                continue
            raise error
        result[r_key] = _property(data, key, inner, opt)
        data[r_key] = data[key]
        if key != r_key:
            del data[key]
    return result, None


def _resolve_tuple(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, (list, tuple)):
        raise ValidationError("expected array but got " + js_to_string(data), opt)
    items = schema.list or []
    result = [_property(data, index, inner, opt) for index, inner in enumerate(items)]
    if strict:
        return result, None
    result.extend(data[len(items):])
    return result, None


def _resolve_object(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, dict):
        raise ValidationError("expected object but got " + js_to_string(data), opt)
    sub_dict = schema.dict or {}
    result: Dict[Any, Any] = {}
    for key in _js_own_enumerable_keys(sub_dict):
        value = _property(data, key, sub_dict[key], opt)
        if value is not None or key in data:
            result[key] = value
    if not strict:
        _merge_missing(result, data)
    _js_reorder_mapping(result)
    return result, None


def _resolve_union(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    for inner in schema.list or []:
        try:
            return Schema.resolve(data, inner, opt, strict)
        except Exception:
            continue
    raise ValidationError("expected {} but got {}".format(schema.to_string(), _json_stringify(data)), opt)


def _resolve_intersect(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    items = schema.list or []
    if not items:
        return data, None
    message = "expected {} but got {}".format(schema.to_string(), _json_stringify(data))
    result: Any = None
    for inner in items:
        value = Schema.resolve(data, inner, opt, True)[0]
        if is_nullable(value):
            continue
        if is_nullable(result):
            result = value
        elif _value_typeof(result) != _value_typeof(value):
            raise ValidationError(message, opt)
        elif isinstance(value, (dict, list, tuple)):
            if result is None:
                result = {}
            _merge_missing(result, value)
        elif result != value:
            raise ValidationError(message, opt)
    if not strict and isinstance(data, dict):
        if result is None:
            # The reference's `merge(undefined, data)` throws through
            # `key in undefined` as soon as the object has a key, and yields
            # `undefined` for an empty one.
            keys = _js_own_enumerable_keys(data)
            if keys:
                raise TypeError("Cannot use 'in' operator to search for '{}' in undefined".format(keys[0]))
            return None, None
        _merge_missing(result, data)
    return result, None


def _resolve_transform(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    inner = schema.inner if isinstance(schema.inner, Schema) else Schema.any()
    result, adapted = Schema.resolve(data, inner, opt, True)
    if adapted is None:
        adapted = data
    callback = schema.callback
    if not callable(callback):
        raise TypeError("Schema(transform) callback is not callable (got {}: {!r})".format(type(callback).__name__, callback))
    if schema.preserve:
        return _call_with_arity(callback, (result, opt)), None
    return _call_with_arity(callback, (result, opt)), _call_with_arity(callback, (adapted, opt))


# Register all standard resolvers
Schema.extend("lazy", _resolve_lazy)
Schema.extend("any", _resolve_any)
Schema.extend("never", _resolve_never)
Schema.extend("const", _resolve_const)
Schema.extend("string", _resolve_string)
Schema.extend("number", _resolve_number)
Schema.extend("boolean", _resolve_boolean)
Schema.extend("bitset", _resolve_bitset)
Schema.extend("function", _resolve_function)
Schema.extend("is", _resolve_is)
Schema.extend("array", _resolve_array)
Schema.extend("dict", _resolve_dict)
Schema.extend("tuple", _resolve_tuple)
Schema.extend("object", _resolve_object)
Schema.extend("union", _resolve_union)
Schema.extend("intersect", _resolve_intersect)
Schema.extend("transform", _resolve_transform)

# Export shorthand alias 'z' matching Schemastery / Zod convention
z = Schema
