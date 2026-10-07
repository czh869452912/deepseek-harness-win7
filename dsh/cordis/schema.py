"""
Schemastery: Runtime schema validation & type specification DSL for Cordis
1:1 matching reference/vendor/schemastery/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.

Language and platform adaptations, all recorded at their call site:

* JavaScript `undefined` has no Python value; the port reads it back as `None`
  and renders it as `null` in serialized output, except where the reference
  keeps the two apart: `Schema.resolve` reports an omitted adapted member as the
  port's `undefined` sentinel (`dsh.cordis.utils._UNDEFINED`), so a resolver's
  explicit `None` stays the reference's `null` and is written back.
* `Object.assign` copies a schema's own properties by reference, so `_clone`
  shares containers; a JavaScript `new Function('return ' + source)()` cannot
  rehydrate a Python callback, so the constructor keeps the callback source and
  a rehydrated transform fails loud when it is validated.
* A property the reference never assigns is not `undefined` for Python either:
  the factories leave `preserve` and the `const` value unassigned, so `toJSON()`
  drops a member that was never supplied while keeping an assigned `null`,
  `false`, `0`, `[]` or `{}`, exactly as `JSON.stringify` does.
* The reference's transform resolver calls `callback!(result)` with exactly one
  positional argument, so a callback that declares more parameters reads
  `undefined` for them; Python raises for the same call, so the port passes the
  port's nullish value for every declared parameter after the first.
* The reference's `Schema.lazy` keeps a `{ toJSON }` stub object as the node's
  `inner` until the deferred schema is built; the port stores the port's
  nullish value there and keeps the stub's node in `lazy_origin` instead
  (LEGAL_ADAPTATION), so `inner` reads as `None` before the build.
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

# index.ts:1 imports `deepEqual` from @deepseek-ai/cosmokit, so the schema port
# consumes the one canonical comparison the rest of the port already carries
# (utils.py mirrors cosmokit src/types.ts:118-142) rather than a private copy.
# `is_nullable` is imported instead of redefined locally so the sentinel-aware
# cosmokit predicate (utils.py:1007) is the single nullish test used here.
from dsh.cordis.utils import (
    _UNDEFINED,
    _js_own_enumerable_keys,
    _js_reorder_mapping,
    _js_string_length,
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
    strict)` and every `ignore` predicate as `ignore(data, schema)`; a
    JavaScript callee that declares fewer parameters ignores the extra
    arguments.  Python raises `TypeError` for the same call, so this port passes
    exactly the leading arguments the callee declares (LEGAL_ADAPTATION).  The
    transform callback is the exception: the reference passes it exactly one
    argument, so `_call_transform_callback` fills the remaining declared
    parameters with the port's nullish value instead.
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


def _declared_positional_count(fn: Callable[..., Any]) -> Optional[int]:
    """
    Count the positional parameters `fn` declares, or `None` when it takes `*args`.

    Unlike `_positional_arity` this is uncapped, because the transform resolver
    has to supply the port's nullish value for every parameter the callback
    declares after the first one the reference actually passes.
    """
    try:
        parameters = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        # A callee without an inspectable signature observes the reference's
        # single argument.
        return None
    count = 0
    for parameter in parameters:
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            count += 1
        elif parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return None
    return count


def _call_transform_callback(callback: Callable[..., Any], value: Any) -> Any:
    """
    Call a transform callback the way the reference's transform resolver does.

    The reference formats both the resolved and the adapted value through
    `callback!(value)` with exactly one positional argument, so a callback that
    declares further parameters reads `undefined` for them.  Python raises
    `TypeError` for the same call, so the port supplies the port's nullish value
    for every parameter the callback declares after the first
    (LEGAL_ADAPTATION).
    """
    declared = _declared_positional_count(callback)
    if declared is None:
        # A `*args` callee sees the reference's single argument.
        return callback(value)
    if declared == 0:
        return callback()
    return callback(value, *([None] * (declared - 1)))


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


def _json_safe(value: Any) -> Any:
    """
    The value `JSON.stringify` would store for a node member.

    The reference serializes every node through `JSON.stringify`, which renders
    a non-finite number as `null` and enumerates an object's own members in
    ECMAScript order.  Python has no `NaN`/`Infinity` JSON literal, so the port
    normalizes them here (LEGAL_ADAPTATION).
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(value[key]) for key in _js_own_enumerable_keys(value)}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _for_in_keys(value: Any) -> List[Any]:
    """
    The keys a `for (const key in value)` loop enumerates.

    An array, string or `ArrayBufferView` enumerates its indices, a plain object
    its own enumerable keys, and a primitive no key at all; the port's
    `simplify()` object/dict branches read their members through this.
    """
    if isinstance(value, (list, tuple, memoryview)):
        return [str(index) for index in range(len(value))]
    if isinstance(value, str):
        return [str(index) for index in range(len(value))]
    return _js_own_enumerable_keys(value)


def _for_in_member(value: Any, key: Any) -> Any:
    """`value[key]` for a key `_for_in_keys` produced."""
    if isinstance(key, str) and key.isascii() and key.isdigit():
        # An index key a container enumerates indexes its own elements, as
        # `value["0"]` does in the reference.
        index = int(key)
        if isinstance(value, (list, tuple, str, memoryview)) and 0 <= index < len(value):
            return value[index]
    return _read_key(value, key)


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


def _shared_badges(meta: Dict[str, Any]) -> List[Dict[str, str]]:
    """`meta.badges ||= []`, which assigns into the meta object passed in."""
    badges = meta.get("badges")
    if not badges:
        badges = []
        meta["badges"] = badges
    return badges


def _get_inner(value: Any) -> Any:
    """`getInner(value)` from the reference's `i18n`: `value?.$value ?? value?.$inner`."""
    if not isinstance(value, dict):
        return None
    member = value.get("$value")
    if member is not None:
        return member
    return value.get("$inner")


def _extract_keys(value: Any) -> Dict[Any, Any]:
    """`extractKeys(value)`: `filterKeys(value ?? {}, key => !key.startsWith('$'))`."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return {
            key: value[key]
            for key in _js_own_enumerable_keys(value)
            if not str(key).startswith("$")
        }
    if isinstance(value, (list, tuple, str, memoryview)):
        # `Object.entries` of a sequence or string yields its index keys.
        return {str(index): value[index] for index in range(len(value))}
    return {}


def _merge_desc(original: Any, messages: Dict[Any, Any]) -> Dict[str, Any]:
    """`mergeDesc(original, messages)` from the reference's `i18n`."""
    if isinstance(original, str):
        result: Dict[str, Any] = {"": original}
    elif isinstance(original, dict):
        result = dict(original)
    else:
        result = {}
    for locale in _js_own_enumerable_keys(messages):
        value = messages[locale]
        desc = None
        if isinstance(value, dict):
            desc = value.get("$description") or value.get("$desc")
        if desc:
            result[locale] = desc
        elif isinstance(value, str):
            result[locale] = value
    return result


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


class _Unset:
    """
    Stand-in for a JavaScript property the reference never assigned.

    `Schema.const(undefined)` and `Schema.const(null)` are the same call in
    Python, so the `const` factory records whether a constant was supplied at
    all and leaves the member out of the serialized node when it was not.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "undefined"


#: Omitted-argument marker for `Schema.const()`.
_UNSET = _Unset()


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


#: Reference member names that differ from the port's attribute spelling.
_REFERENCE_ATTRIBUTES = {"sKey": "s_key"}


class _SchemaMeta(type):
    """
    Callable constructor matching the reference's `Schema(options)`.

    The reference constructor returns a *referenced* node instead of a fresh one
    when `options.refs` carries a serialized envelope.  Python cannot express
    that from `__new__`, because the follow-up `__init__` call would then
    re-initialize the shared node, so the hydration branch lives in the
    metaclass and `Schema(node)` still builds an ordinary node.
    """

    def __call__(cls, options: Optional[Dict[str, Any]] = None) -> "Schema":
        refs = options.get("refs") if isinstance(options, dict) else None
        if refs is not None:
            return cls._hydrate_refs(options, refs)
        if isinstance(options, Schema):
            # `Schema(this)` in the reference: `Object.assign` copies the own
            # members by reference and the copy takes a fresh uid.
            return options._clone()
        return super().__call__(options)


# `deepEqual`, `isNullable` and `clone` are Cosmokit helpers shared with the
# framework layer; the port re-exports them under the names Schemastery's
# resolvers and `simplify()` call.
class Schema(metaclass=_SchemaMeta):
    """
    Schemastery Schema definition matching reference/vendor/schemastery/src/index.ts.
    Provides fluent builder methods, validation, simplification, i18n, and JSON serialization.
    """

    resolvers: Dict[str, Callable[..., Any]] = {}

    #: `Schema.ValidationError`, the class the README's extensibility example
    #: throws from a custom resolver.
    ValidationError = ValidationError

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
        #: `None` is the reference's `preserve: undefined`, so an unassigned
        #: flag stays out of the serialized node while an assigned `false` is
        #: kept.
        self.preserve: Optional[bool] = None
        #: Whether the node carries a `value` member at all, which is what
        #: separates `Schema.const(null)` from `Schema.const(undefined)`.
        self.value_provided: bool = False

        if options:
            opts = dict(options)
            opts.pop("uid", None)
            self.value_provided = "value" in opts
            cb = opts.get("callback")
            if cb is not None and not callable(cb):
                opts.pop("callback")
                self.callback_source = str(cb)
            for k, v in opts.items():
                setattr(self, _REFERENCE_ATTRIBUTES.get(k, k), v)
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
        s.value_provided = getattr(self, "value_provided", False)
        if getattr(self, "_dynamic", False):
            s._dynamic = True
        # `Schema.lazy`'s inner stub keeps a closure over the node that
        # created it, so a clone serializes that node's built schema.
        if getattr(self, "lazy_origin", None) is not None:
            s.lazy_origin = self.lazy_origin
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
        """Add a deprecated badge, as the reference's `meta.badges ||= []` push does."""
        # `Schema(this)` shares the meta object, so the source schema lists
        # the badge too, exactly as the reference mutates it.
        s = self._clone()
        badges = _shared_badges(s.meta)
        badges.append({"text": "deprecated", "type": "danger"})
        return s

    def experimental(self) -> "Schema":
        """Add an experimental badge, sharing the source schema's meta object."""
        s = self._clone()
        badges = _shared_badges(s.meta)
        badges.append({"text": "experimental", "type": "warning"})
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
        """
        Attach localized descriptions matching TS `Schema.prototype.i18n()`.

        The reference merges a locale message into the description only when the
        message carries `$description`/`$desc` or is a plain string, writes the
        result into the meta object the clone shares with its source, and passes
        each relation member the message entry `getInner(data)?.[key] ??
        data?.[key]` finds.
        """
        s = self._clone()
        desc = _merge_desc(s.meta.get("description"), messages)
        if desc:
            s.meta["description"] = desc

        if s.dict:
            new_dict = {}
            for key in _js_own_enumerable_keys(s.dict):
                sub_msg = {}
                for locale in _js_own_enumerable_keys(messages):
                    data = messages[locale]
                    member = _for_in_member(_get_inner(data), key)
                    if member is None:
                        member = _for_in_member(data, key)
                    sub_msg[locale] = member
                new_dict[key] = s.dict[key].i18n(sub_msg)
            s.dict = new_dict

        if s.list:
            new_list = []
            for index, inner in enumerate(s.list):
                sub_msg = {}
                for locale in _js_own_enumerable_keys(messages):
                    data = messages[locale]
                    inner_value = _get_inner(data)
                    if isinstance(inner_value, (list, tuple)):
                        member = inner_value[index] if index < len(inner_value) else None
                    elif isinstance(data, (list, tuple)):
                        member = data[index] if index < len(data) else None
                    else:
                        member = _extract_keys(data)
                    sub_msg[locale] = member
                new_list.append(inner.i18n(sub_msg))
            s.list = new_list

        if s.inner is not None or s.type == "lazy":
            # A lazy node keeps its `{ toJSON }` stub as `inner` until a
            # resolution or serialization replaces it; the stub has no
            # `i18n`, so localizing an unbuilt lazy schema fails loud.
            if not isinstance(s.inner, Schema):
                raise TypeError("schema.inner.i18n is not a function")
            sub_msg = {}
            for locale in _js_own_enumerable_keys(messages):
                data = messages[locale]
                inner_value = _get_inner(data)
                sub_msg[locale] = inner_value if inner_value else _extract_keys(data)
            s.inner = s.inner.i18n(sub_msg)

        if s.s_key:
            sub_msg = {}
            for locale in _js_own_enumerable_keys(messages):
                data = messages[locale]
                sub_msg[locale] = data.get("$key") if isinstance(data, dict) else None
            s.s_key = s.s_key.i18n(sub_msg)

        return s

    def simplify(self, value: Any = None) -> Any:
        """Strip values equal to default schema values matching TS Schema.simplify().

        index.ts:408/417 compare unconditionally against ``this.meta.default``,
        which is ``undefined`` when the schema never set one, so the port reads
        the missing meta key as its ``undefined`` sentinel rather than skipping
        the comparison.  The third argument is the reference's ``strict`` flag
        (``this.type === 'dict'``), which cosmokit forwards into the object
        fallback (types.ts:141) but not into array elements (types.ts:129).
        """
        default_val = self.meta.get("default", _UNDEFINED)
        if deep_equal(value, default_val, self.type == "dict"):
            return None
        if is_nullable(value):
            return value

        if self.type in ("object", "dict"):
            # The reference walks `for (const key in value)`, so a non-object
            # input still yields its enumerable keys instead of being returned
            # unchanged.
            res: Dict[str, Any] = {}
            for key in _for_in_keys(value):
                schema = (self.dict or {}).get(key) if self.type == "object" else self.inner
                # `schema?.simplify(value[key])` keeps `undefined` for a member
                # the schema does not declare, which the nullish test below then
                # drops for an object and keeps for a dict.
                item = schema.simplify(_for_in_member(value, key)) if schema is not None else None
                if self.type == "dict" or not is_nullable(item):
                    res[key] = item
            if deep_equal(res, default_val, self.type == "dict"):
                return None
            return res
        elif self.type in ("array", "tuple"):
            if not isinstance(value, (list, tuple)):
                # `(value as any[]).forEach(...)` is a TypeError for any value
                # without `forEach`, which the port reproduces instead of
                # returning the input unchanged.
                raise TypeError("value.forEach is not a function")
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

    #: Members the reference's factory assigns after `meta`, in the order its
    #: `defineMethod` key list assigns them; `{ ...schema }` serializes in the
    #: property creation order, so the node carries the same member order.
    _RELATION_KEYS: Dict[str, Tuple[str, ...]] = {
        "is": ("constructor",),
        "const": ("value",),
        "bitset": ("bits",),
        "array": ("inner",),
        "dict": ("inner", "sKey"),
        "tuple": ("list",),
        "union": ("list",),
        "intersect": ("list",),
        "object": ("dict",),
        "transform": ("inner", "callback", "preserve"),
    }

    def _serialized_lazy_inner(self) -> Optional["Schema"]:
        """
        The schema a lazy node's `inner` member serializes as.

        The reference's lazy node holds a `{ toJSON }` stub as `inner` whose
        closure builds the node `Schema.lazy()` created and merges that node's
        meta, so serializing a clone of a lazy schema reports the original's
        built node while a node already carrying a real `inner` reports that
        one. The port spells the same origin relationship with `lazy_origin`.
        """
        if isinstance(self.inner, Schema):
            return self.inner
        origin = getattr(self, "lazy_origin", None)
        if origin is None:
            origin = self
        if not isinstance(origin.inner, Schema):
            origin.inner = _built_lazy_inner(origin)
        return origin.inner

    def _own_members(self) -> Iterator[Tuple[str, Any]]:
        """
        Own enumerable members of this node in the reference's creation order.

        The reference serializes a node with
        `JSON.parse(JSON.stringify({ ...this }))`: `type` comes from the
        constructor options, `meta` from the constructor's `schema.meta ||= {}`,
        and every remaining member from the factory's key list.  A member the
        factory never assigned is `undefined` and therefore absent from the
        serialized node, while an assigned `null`, `false`, `0`, `[]` or `{}` is
        kept.
        """
        yield "type", self.type
        if self.type == "lazy":
            # `Schema.lazy` passes `{ type, builder, inner }` to the
            # constructor and `builder` is a function that JSON drops, so
            # `inner` precedes the constructor's `meta` here.
            yield "inner", self._serialized_lazy_inner()
            yield "meta", _json_safe(dict(self.meta))
            return
        yield "meta", _json_safe(dict(self.meta))
        for key in self._RELATION_KEYS.get(self.type, ()):
            if key == "value":
                if self.value_provided or self.value is not None:
                    yield "value", _json_safe(self.value)
            elif key == "preserve":
                if self.preserve is not None:
                    yield "preserve", self.preserve
            elif key == "callback":
                source = _callback_source(self)
                if source is not None:
                    yield "callback", source
            elif key == "constructor":
                if self.constructor is not None:
                    if isinstance(self.constructor, type):
                        yield "constructor", self.constructor.__name__
                    else:
                        yield "constructor", str(self.constructor)
            elif key == "sKey":
                if self.s_key is not None:
                    yield "sKey", self.s_key
            else:
                member = getattr(self, key)
                if member is not None:
                    yield key, _json_safe(member)

    def _collect_node(self, refs: Dict[int, Dict[str, Any]]) -> int:
        """Register this node in `refs` once and return its uid."""
        if self.uid in refs:
            return self.uid
        node: Dict[str, Any] = {}
        refs[self.uid] = node
        for key, member in self._own_members():
            if key in ("inner", "sKey"):
                # A lazy node whose builder yields no schema carries no
                # `inner` member, as the reference's stub-less node does not.
                if member is not None:
                    node[key] = member.toJSON(refs)
            elif key == "list":
                node[key] = [item.toJSON(refs) for item in member]
            elif key == "dict":
                node[key] = {name: member[name].toJSON(refs) for name in _js_own_enumerable_keys(member)}
            else:
                node[key] = member
        return self.uid

    def toJSON(self, refs_collector: Optional[Dict[int, Dict[str, Any]]] = None) -> Union[int, Dict[str, Any]]:
        """
        Serialize this schema with a flat reference table, matching TS `Schema.prototype.toJSON()`.

        The root call returns the `{ uid, refs }` envelope, where `refs` is
        keyed by uid and every node carries its relations as uids so that shared
        and recursive nodes are serialized once; a nested call returns the
        node's uid, which is what the reference's `toJSON` returns while
        `__schemastery_refs__` is set.
        """
        is_root = refs_collector is None
        if is_root:
            refs: Dict[int, Dict[str, Any]] = {}
        else:
            refs = refs_collector
        self._collect_node(refs)
        if is_root:
            # Every `refs` key is a uid, and ECMAScript enumerates integer-like
            # own keys in ascending order however they were inserted, so the
            # envelope lists the nodes by ascending uid.
            return {"uid": self.uid, "refs": {str(uid): refs[uid] for uid in sorted(refs)}}
        return self.uid

    def to_json(self) -> Dict[str, Any]:
        """
        Port-only nested serialization; the canonical wire form is `toJSON()`.

        This helper predates the `{ uid, refs }` envelope and keeps the same own
        member order and the same falsey/nullable members, nesting every
        relation instead of referencing it by uid.
        """
        res: Dict[str, Any] = {"uid": self.uid}
        for key, member in self._own_members():
            if key in ("inner", "sKey"):
                if member is not None:
                    res[key] = member.to_json()
            elif key == "list":
                res[key] = [item.to_json() for item in member]
            elif key == "dict":
                res[key] = {name: member[name].to_json() for name in _js_own_enumerable_keys(member)}
            else:
                res[key] = member
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
            if self.value_provided:
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
            if self.value is None:
                # The reference's formatter returns the raw constant and
                # `Schema.prototype.toString` falls back to `Schema<const>` when
                # that is nullish, so both `const(null)` and `const(undefined)`
                # print the fallback (LEGAL_ADAPTATION for the non-null case,
                # where Python has no non-str return).
                return "Schema<const>"
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
            # The reference parenthesizes the joined members for every inline
            # call, including a union with a single member.
            return "({})".format(result) if inline else result
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
    def _hydrate_refs(cls, envelope: Dict[str, Any], refs_payload: Dict[Any, Any]) -> "Schema":
        """
        `Schema({ uid, refs })`: rebuild every referenced node and return the root.

        The reference maps `refs` through `new Schema(options)`, links each node
        with `getRef`, and returns `refs[options.uid]`; every rebuilt node takes
        a fresh uid, so a rehydrated tree renumbers.  A relation uid the payload
        does not carry becomes the port's nullish value, which is what
        `refs[uid]` reads as `undefined` in the reference.

        Permitted ADAPT deviation: the reference rehydrates a serialized
        callback with `new Function('return ' + source)()`.  Python 3.8 does not
        evaluate serialized source, so a node's callback stays uncallable with
        its source in `callback_source` and `_resolve_transform` raises a 1:1
        fail-loud `TypeError` when the rehydrated transform is validated.
        """
        nodes: Dict[str, "Schema"] = {}
        for uid in _js_own_enumerable_keys(refs_payload):
            nodes[str(uid)] = cls(refs_payload[uid])

        def get_ref(uid: Any) -> Any:
            if uid is None:
                return None
            return nodes.get(str(uid))

        for uid in _js_own_enumerable_keys(refs_payload):
            node = refs_payload[uid]
            schema = nodes[str(uid)]
            if not isinstance(node, dict):
                continue
            schema.s_key = get_ref(node.get("sKey", node.get("s_key")))
            schema.inner = get_ref(node.get("inner"))
            if node.get("list") is not None:
                schema.list = [get_ref(item) for item in node["list"]]
            if node.get("dict") is not None:
                member_dict = node["dict"]
                schema.dict = {name: get_ref(member_dict[name]) for name in _js_own_enumerable_keys(member_dict)}
        return nodes.get(str(envelope.get("uid")))

    @classmethod
    def from_json(cls, payload: Dict[str, Any]) -> "Schema":
        """
        Port-only alias for `Schema(payload)` (the reference's callable constructor).

        Prefer `Schema(payload)`, which is the reference contract; this alias
        exists for the port's earlier callers and delegates to the same
        hydration path.
        """
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
    def const_(cls, value: Any = _UNSET) -> "Schema":
        """
        `Schema.const(value)`.

        An omitted value stays unassigned, which is the reference's
        `Schema.const(undefined)` and serializes without a `value` member; an
        explicit `None` is `Schema.const(null)` and keeps `value: null`.
        """
        options: Dict[str, Any] = {"type": "const"}
        if value is not _UNSET:
            options["value"] = value
        return cls(options)

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
    def bitset(cls, bits: Dict[str, Any]) -> "Schema":
        """
        `Schema.bitset(bits)`.

        The reference keeps every member whose value passes `typeof value ===
        'number'`, so a fractional, `NaN` or infinite bit stays in the
        definition and is only coerced with `ToInt32` where the resolver masks
        with it.  Members with any other value (`true`, `'2'`) are dropped.
        """
        clean_bits = {
            key: bits[key]
            for key in _js_own_enumerable_keys(bits)
            if isinstance(bits[key], (int, float)) and not isinstance(bits[key], bool)
        }
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
        # The reference creates the node first and resolves `inner` afterwards,
        # which fixes the uid order of the serialized node graph.
        s = cls({"type": "array"})
        s.inner = cls.from_(inner)
        s.meta["default"] = []
        return s

    @classmethod
    def dict(cls, inner: Any, s_key: Any = None) -> "Schema":
        # The reference creates the `dict` node first, then resolves `inner` and
        # only afterwards falls back to `Schema.string()` for an omitted key
        # schema, which fixes the uid order of the serialized node graph.
        s = cls({"type": "dict"})
        s.inner = cls.from_(inner)
        s.s_key = cls.from_(s_key) if s_key is not None else cls.string()
        s.meta["default"] = {}
        return s

    @classmethod
    def tuple(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        s = cls({"type": "tuple"})
        s.list = [cls.from_(item) for item in list_types]
        s.meta["default"] = []
        return s

    @classmethod
    def object(cls, dict_types: Dict[str, Any]) -> "Schema":
        s = cls({"type": "object"})
        # The reference maps the member object with `valueMap`, which enumerates
        # `Object.keys`, so integer-like member names come first.
        s.dict = {key: cls.from_(dict_types[key]) for key in _js_own_enumerable_keys(dict_types)}
        s.meta["default"] = {}
        return s

    @classmethod
    def union(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        s = cls({"type": "union"})
        s.list = [cls.from_(item) for item in list_types]
        return s

    @classmethod
    def intersect(cls, *args: Any) -> "Schema":
        list_types = args[0] if len(args) == 1 and isinstance(args[0], (list, tuple)) else list(args)
        s = cls({"type": "intersect"})
        s.list = [cls.from_(item) for item in list_types]
        return s

    @classmethod
    def transform(cls, inner: Any, callback: Callable[..., Any], preserve: Optional[bool] = None) -> "Schema":
        """
        `Schema.transform(inner, callback, preserve?)`.

        An omitted `preserve` stays `undefined` and is absent from the
        serialized node, while an explicit `false` is kept.
        """
        s = cls({"type": "transform", "callback": callback, "preserve": preserve})
        # The reference assigns `inner` after creating the node.
        s.inner = cls.from_(inner)
        return s

    @classmethod
    def lazy(cls, builder: Callable[[], "Schema"]) -> "Schema":
        # The reference stores a `{ toJSON }` stub whose closure builds the
        # node this factory returned, so the stub outlives clones of it; the
        # port keeps that node in `lazy_origin` and leaves `inner` nullish
        # until the deferred schema is built.
        s = cls({"type": "lazy", "builder": builder})
        s.lazy_origin = s
        return s

    @classmethod
    def dynamic(cls, builder: Callable[..., "Schema"]) -> "Schema":
        """Dynamic schema factory matching TS Schemastery.dynamic."""
        return cls({"type": "lazy", "builder": builder, "_dynamic": True})

    @classmethod
    def computed(cls, callback: Callable[..., Any]) -> "Schema":
        """Computed schema property based on context or sibling values."""
        def _resolve_computed(data: Any, opt: Any = None) -> Any:
            # Port-only factory: the reference has no `computed`, and a transform
            # callback only ever receives the resolved value, so the callback
            # sees the root value the context supplied or the value itself.
            root = (opt or {}).get("root", data)
            return _call_with_arity(callback, (root,))
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

        Returns `(value, adapted)`, the reference's `[value, adapted?]` result:
        `adapted` is the port's `undefined` sentinel where the reference returned
        a one-element tuple, and the adapted value itself otherwise, so a
        resolver's explicit `None` is the reference's `null` for `_property`,
        which writes every adapted value back into the validated container.
        """
        opt = options or {}
        if not schema:
            return data, _UNDEFINED

        ignore_fn = opt.get("ignore")
        if callable(ignore_fn) and _call_with_arity(ignore_fn, (data, schema)):
            return data, _UNDEFINED

        if is_nullable(data) and schema.type != "lazy":
            if schema.meta.get("required"):
                raise ValidationError("missing required value", opt)
            fallback = schema.meta.get("default")
            current = schema
            while current is not None and getattr(current, "type", None) == "intersect" and is_nullable(fallback):
                current = current.list[0] if getattr(current, "list", None) else None
                fallback = current.meta.get("default") if current is not None else None
            if is_nullable(fallback):
                return data, _UNDEFINED
            data = clone(fallback)

        callback = cls.resolvers.get(schema.type)
        if not callback:
            raise ValidationError('unsupported type "{}"'.format(schema.type), opt)

        try:
            result = _call_with_arity(callback, (data, schema, opt, strict))
        except Exception as error:
            if not schema.meta.get("loose"):
                raise error
            return schema.meta.get("default"), _UNDEFINED
        if isinstance(result, (list, tuple)):
            return result[0], result[1] if len(result) > 1 else _UNDEFINED
        return result, _UNDEFINED


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


def _built_lazy_inner(schema: Schema) -> Schema:
    """
    Build a lazy node's deferred schema and merge the node's meta into it.

    The reference reads `schema.inner!.meta` after calling `schema.builder!()`,
    so a missing builder and a builder that yields no schema both fail loud.
    A node `Schema.lazy()` did not create carries no builder at all, and
    building it is a port-only path the reference reaches as
    `undefined[kSchema]` instead.
    """
    builder = getattr(schema, "builder", None)
    if not callable(builder):
        raise TypeError("schema.builder is not a function")
    built = builder()
    if not isinstance(built, Schema):
        raise TypeError("Cannot read properties of {} (reading 'meta')".format(js_to_string(built)))
    built.meta = {**schema.meta, **built.meta}
    return built


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
        schema.inner = _built_lazy_inner(schema)
    return Schema.resolve(data, schema.inner, opt, strict)


def _resolve_any(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    return data, _UNDEFINED


def _resolve_never(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    raise ValidationError("expected nullable but got " + js_to_string(data), opt)


def _resolve_const(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if deep_equal(data, schema.value):
        return schema.value, _UNDEFINED
    expected = js_to_string(schema.value) if schema.value_provided else "undefined"
    raise ValidationError("expected {} but got {}".format(expected, js_to_string(data)), opt)


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
    _check_range(_js_string_length(data), schema.meta, "string length", opt)
    return data, _UNDEFINED


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
    return data, _UNDEFINED


def _resolve_boolean(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if isinstance(data, bool):
        return data, _UNDEFINED
    raise ValidationError("expected boolean but got " + js_to_string(data), opt)


def _resolve_bitset(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    bits = schema.bits or {}
    value = 0
    keys: List[Any] = []
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        value = data
        numeric = _to_int32(data)
        for key in _js_own_enumerable_keys(bits):
            # The reference's `data & bits[key]` coerces both operands with
            # `ToInt32`, so a fractional or non-finite bit masks as its int32
            # value.
            if numeric & _to_int32(bits[key]):
                keys.append(key)
    elif isinstance(data, (list, tuple)):
        keys = list(data)
        for key in keys:
            if not isinstance(key, str):
                raise ValidationError("expected string but got " + js_to_string(key), opt)
            if key in bits:
                value = _to_int32(value) | _to_int32(bits[key])
    else:
        raise ValidationError("expected number or array but got " + js_to_string(data), opt)
    if value == schema.meta.get("default"):
        return value, _UNDEFINED
    return value, keys


def _resolve_function(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if callable(data):
        return data, _UNDEFINED
    raise ValidationError("expected function but got " + js_to_string(data), opt)


def _resolve_is(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    constructor = schema.constructor
    if isinstance(constructor, type):
        if isinstance(data, constructor):
            return data, _UNDEFINED
        raise ValidationError("expected {} but got {}".format(constructor.__name__, js_to_string(data)), opt)
    if callable(constructor):
        # The reference's `data instanceof constructor` walks the data's
        # prototype chain; a Python class chain can only contain the callable
        # itself, so a non-class callable matches nothing.
        for base in type(data).__mro__:
            if base is constructor:
                return data, _UNDEFINED
        raise ValidationError("expected {} but got {}".format(getattr(constructor, "__name__", js_to_string(constructor)), js_to_string(data)), opt)
    if is_nullable(data):
        raise ValidationError("expected {} but got {}".format(js_to_string(constructor), js_to_string(data)), opt)
    for base in type(data).__mro__:
        if base.__name__ == constructor:
            return data, _UNDEFINED
    raise ValidationError("expected {} but got {}".format(js_to_string(constructor), js_to_string(data)), opt)


def _property(data: Any, key: Any, schema: Schema, opt: Dict[str, Any]) -> Any:
    """
    Validate one container member, writing an adapted value back to `data`.

    The reference writes back every adapted value except `undefined`, so an
    explicit `null` adaptation lands in the container while a resolver that
    adapted nothing leaves the member untouched.
    """
    sub_opt = {**opt, "path": list(opt.get("path") or []) + [key]}
    try:
        res, adapted = Schema.resolve(_read_key(data, key), schema, sub_opt)
        if adapted is not _UNDEFINED:
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
    return [_property(data, index, inner, opt) for index in range(len(data))], _UNDEFINED


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
    return result, _UNDEFINED


def _resolve_tuple(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    if not isinstance(data, (list, tuple)):
        raise ValidationError("expected array but got " + js_to_string(data), opt)
    items = schema.list or []
    result = [_property(data, index, inner, opt) for index, inner in enumerate(items)]
    if strict:
        return result, _UNDEFINED
    result.extend(data[len(items):])
    return result, _UNDEFINED


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
    return result, _UNDEFINED


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
        return data, _UNDEFINED
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
            return None, _UNDEFINED
        _merge_missing(result, data)
    return result, _UNDEFINED


def _resolve_transform(data: Any, schema: Schema, opt: Dict[str, Any], strict: bool) -> Tuple[Any, Any]:
    """
    `transform` resolver.

    The reference destructures `[result, adapted = data]`, so the default
    replaces an omitted adapted member only: an adapted `null` reaches both
    callback calls.  The callback's own result is the node's adapted value, and
    its `None` is the reference's `null`; a callback that adapts nothing returns
    the port's `undefined` sentinel (LEGAL_ADAPTATION for a callback the
    reference leaves without a `return`, which yields `undefined`).
    """
    inner = schema.inner if isinstance(schema.inner, Schema) else Schema.any()
    result, adapted = Schema.resolve(data, inner, opt, True)
    if adapted is _UNDEFINED:
        adapted = data
    callback = schema.callback
    if not callable(callback):
        raise TypeError("Schema(transform) callback is not callable (got {}: {!r})".format(type(callback).__name__, callback))
    applied = _call_transform_callback(callback, result)
    if schema.preserve:
        return applied, _UNDEFINED
    return applied, _call_transform_callback(callback, adapted)


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
