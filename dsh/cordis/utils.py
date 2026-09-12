"""
Cordis Utilities matching reference/vendor/cordis/src/utils.ts
Implements DisposableList, Symbol constants, Traceable proxy, and Stack builders.
"""

import base64
import binascii
import calendar
import copy
import functools
import inspect
import sys
import math
import re
import datetime
import time
import traceback
import types
import weakref
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, Set, Tuple, TypeVar, Union

T = TypeVar("T")

_REGEX_TYPE = type(re.compile(""))

#: Python values whose ECMAScript ``typeof`` is ``'function'`` (classes are
#: ``instanceof Function`` in the reference as well).
_JS_FUNCTION_TYPES = (
    types.FunctionType,
    types.LambdaType,
    types.MethodType,
    types.BuiltinFunctionType,
    types.BuiltinMethodType,
    types.MethodWrapperType,
    type,
    functools.partial,
)

#: A canonical array index key: ``"0"``, ``"1"``, ... with no sign, leading
#: zero, fraction or exponent (ECMA-262 ``Array index`` before the 2**32 - 1
#: bound, which `_js_own_key_order` applies).
_JS_ARRAY_INDEX = re.compile(r"^(?:0|[1-9][0-9]*)\Z", re.ASCII)

# ---------------------------------------------------------------------------
# ECMAScript runtime semantics helpers
#
# The authoritative implementation is TypeScript running on an ECMAScript
# engine, so a 1:1 port must reproduce `===`/SameValueZero membership, `typeof`
# buckets, `Math.round`, `Number.prototype.toString`, `String.prototype.padStart`
# and Node's lenient Buffer decoding instead of the nearest Python idiom.
# ---------------------------------------------------------------------------


def _shortest_decimal_digits(value: float) -> Tuple[str, int]:
    """Shortest decimal digits `s` and exponent `n` with value == 0.s * 10**n."""
    text = repr(value)
    exponent = 0
    if "e" in text:
        text, exponent_text = text.split("e")
        exponent = int(exponent_text)
    integer_part, _, fraction_part = text.partition(".")
    combined = integer_part + fraction_part
    point_index = len(integer_part)
    stripped = combined.lstrip("0")
    point_index -= len(combined) - len(stripped)
    return stripped.rstrip("0"), point_index + exponent


def _js_double_to_string(value: float) -> str:
    """ECMAScript `Number::toString` for a double (shortest round-trip form)."""
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"  # String(-0) === "0"
    sign = "-" if value < 0 else ""
    digits, n = _shortest_decimal_digits(abs(value))
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * (-n) + digits
    exponent = n - 1
    mantissa = digits if k == 1 else digits[0] + "." + digits[1:]
    return "%s%se%s%d" % (sign, mantissa, "+" if exponent >= 0 else "-", abs(exponent))


def _js_number_to_string(value: Any) -> str:
    """Render a number like ECMAScript ``Number.prototype.toString``."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        # ECMAScript numbers are doubles: integers beyond 2**53 round first.
        if -9007199254740992 <= value <= 9007199254740992:
            return str(value)
        try:
            return _js_double_to_string(float(value))
        except OverflowError:
            return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, float):
        return _js_double_to_string(value)
    return str(value)


_EPOCH = datetime.datetime(1970, 1, 1)


def _local_utc_offset_seconds() -> float:
    """Local UTC offset in seconds east, using the platform DST state."""
    if time.daylight:
        try:
            if time.localtime().tm_isdst:
                return -time.altzone
        except (OSError, OverflowError, ValueError):
            pass
    return -time.timezone


def _datetime_from_epoch(ts_seconds: float) -> datetime.datetime:
    """``datetime.fromtimestamp`` for instants at or before the epoch.

    LEGAL_ADAPTATION (Windows 7): the Windows C runtime rejects timestamps
    <= 0 (`OSError: [Errno 22]`), while the reference `new Date(ms)` handles
    them. The naive local datetime is rebuilt from the UTC instant plus the
    local offset in that case.
    """
    try:
        return datetime.datetime.fromtimestamp(ts_seconds)
    except (OSError, OverflowError, ValueError):
        return (_EPOCH + datetime.timedelta(seconds=ts_seconds)
                + datetime.timedelta(seconds=_local_utc_offset_seconds()))


def _epoch_seconds_of(value: datetime.datetime) -> float:
    """``Date.valueOf() / 1000`` for a naive local datetime.

    LEGAL_ADAPTATION (Windows 7): `datetime.timestamp()` raises for instants at
    or before the epoch on Windows; the wall-clock delta plus the local offset
    yields the same value there.
    """
    if value.tzinfo is not None:
        return value.timestamp()
    try:
        return value.timestamp()
    except (OSError, OverflowError, ValueError):
        return (value - _EPOCH).total_seconds() - _local_utc_offset_seconds()


def _js_round(value: Any) -> Any:
    """ECMAScript ``Math.round``: ``floor(x + 0.5)`` with NaN/Infinity passthrough."""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return value
    return int(math.floor(value + 0.5))


def _js_pad_start(source: str, length: int) -> str:
    """ECMAScript ``String.prototype.padStart`` (pads before a leading sign too)."""
    if len(source) >= length:
        return source
    return "0" * (length - len(source)) + source


class _UndefinedValue(object):
    """JavaScript ``undefined``: an absent own key, or a missing value.

    Python has no such value, so the port carries a single instance for the one
    place the reference keeps it observable: ``deepEqual`` reads ``a[key]`` and
    ``b[key]`` over the union of both operands' own keys, where a key only one
    operand has reads as ``undefined`` and must stay distinct from ``null``
    (``undefined !== null``) when the comparison is strict.
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return False  # an ECMAScript falsy value

    def __deepcopy__(self, memo: Any) -> "_UndefinedValue":
        """`clone` returns a falsy source unchanged, so the sentinel stays itself.

        The reference opens `clone` with `if (!source || typeof source !==
        'object') return source`, and `undefined` is falsy, so
        ``clone(undefined)`` *is* ``undefined``.  Every nullish check in the
        port recognizes the sentinel by identity, so a deep-copied duplicate
        would stop being nullish and would report as a distinct value
        (``deepEqual([undefined], [clone(undefined)])`` must stay true).
        """
        return self

    def __repr__(self) -> str:
        return "undefined"


#: The port's ``undefined`` (see :class:`_UndefinedValue`).
_UNDEFINED = _UndefinedValue()


def _js_typeof(value: Any) -> str:
    """ECMAScript ``typeof`` bucket of a Python value."""
    if value is _UNDEFINED:
        return "undefined"
    if value is None:
        return "object"  # typeof null === 'object'
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, _JS_FUNCTION_TYPES):
        return "function"
    return "object"


def _js_is_nullish(value: Any) -> bool:
    """ECMAScript ``value == null``, which ``undefined`` satisfies as well."""
    return value is None or value is _UNDEFINED


def _js_is_primitive(value: Any) -> bool:
    """True for a value ECMAScript holds as a primitive rather than an object.

    `Type(V)` is `Object` for every non-primitive value, which is what
    `instanceof` tests before it reads a constructor's prototype.  Python has
    no `symbol`, and the port documents its own mapping for `BigInt` (an
    `int`) and `undefined` (its sentinel).
    """
    return (_js_is_nullish(value) or isinstance(value, bool)
            or isinstance(value, (int, float, str)))


def _js_truthy(value: Any) -> bool:
    """ECMAScript ``ToBoolean``, which Python truthiness is not.

    Only ``undefined``/``null``/``false``/``+0``/``-0``/``NaN``/``''`` are
    falsy in the reference; an empty ``dict``/``set``/``()``/``[]`` is truthy
    there but falsy in Python, so the reference's `&&`/``||`` short-circuits
    cannot be reproduced with Python truthiness.
    """
    if value is _UNDEFINED or value is None or value is False:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return value != 0 and value == value  # +0/-0 and NaN are falsy
    if isinstance(value, str):
        return value != ""
    return True


def _js_number_value(value: Any) -> float:
    """The IEEE-754 double an ECMAScript number holds.

    Every JavaScript number is a double, so two Python integers that differ but
    round to the same double are the *same* value there:
    ``9007199254740992 === 9007199254740993`` is true, and
    ``new Set([9007199254740992, 9007199254740993])`` has one entry.  A Python
    integer past the double range is ``Infinity``, exactly as the reference
    renders such a value (see `_js_number_to_string`).
    """
    if isinstance(value, float):
        return value
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def _js_strict_equal(a: Any, b: Any) -> bool:
    """ECMAScript ``===``, i.e. ``Array.prototype.indexOf`` membership semantics."""
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return False  # NaN === NaN is false even for the same NaN value
    if a is b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        # Both operands compare as the doubles their JavaScript counterparts
        # hold; NaN === NaN is false.
        return _js_number_value(a) == _js_number_value(b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False  # other primitives and all objects compare by reference


def _js_same_value_zero(a: Any, b: Any) -> bool:
    """ECMAScript SameValueZero: ``Array.prototype.includes`` / ``Set`` membership."""
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return _js_strict_equal(a, b)


def _js_membership_key(value: Any) -> Any:
    """Hashable key whose equality matches SameValueZero for a single value."""
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float)):
        # The key carries the double the JavaScript value holds, so integers
        # that differ but round to the same double collapse (see
        # `_js_number_value`); -0 and 0 are the same key under SameValueZero.
        number = _js_number_value(value)
        if math.isnan(number):
            return ("number", "NaN")
        return ("number", number)
    if isinstance(value, str):
        return ("string", value)
    if value is None:
        return ("null", None)
    return ("reference", id(value))


def _js_own_enumerable_keys(value: Any) -> List[Any]:
    """``Object.keys`` for a Python value (dict keys, else instance attributes).

    A `memoryview` is the port's ArrayBufferView, whose own enumerable keys
    are its element indices.  ``weakref.WeakSet``/``weakref.WeakKeyDictionary``
    are the port's WeakSet/WeakMap, and the reference's containers of those
    kinds hold no own properties: their Python internals (the ``data`` set and
    the removal callback) are not JavaScript properties, so the fallback to
    ``__dict__`` must not expose them.
    """
    if isinstance(value, dict):
        return _js_own_key_order(list(value.keys()))
    if isinstance(value, memoryview):
        return [str(index) for index in range(len(value))]
    if isinstance(value, (weakref.WeakSet, weakref.WeakKeyDictionary)):
        return []
    own = getattr(value, "__dict__", None)
    if isinstance(own, dict):
        return _js_own_key_order(list(own.keys()))
    return []


def _js_own_key_order(keys: List[Any]) -> List[Any]:
    """The order ECMAScript enumerates these own keys in.

    ``Object.keys``/``Object.entries``/object spread/``Reflect.ownKeys`` all
    follow ``OrdinaryOwnPropertyKeys``: the array index keys (the canonical
    numeric strings below ``2**32 - 1``, i.e. ``"0"``, ``"1"``, ... but not
    ``"01"``, ``"1.5"``, ``"-1"`` or ``"4294967295"``) in ascending numeric
    order first, then the remaining keys in creation order. A Python dict only
    carries insertion order, so every helper whose result object the reference
    enumerates reorders through here.
    """
    indices: List[int] = []
    others: List[Any] = []
    for key in keys:
        if isinstance(key, str) and _JS_ARRAY_INDEX.match(key) and int(key) < 4294967295:
            indices.append(int(key))
        else:
            others.append(key)
    if not indices:
        return list(keys)
    indices.sort()
    return [str(index) for index in indices] + others


def _js_ordered_mapping(obj: Any) -> Dict[Any, Any]:
    """The plain-object copy of ``obj`` (``{...obj}``) in enumeration order."""
    return {key: _js_read_key(obj, key) for key in _js_own_enumerable_keys(obj)}


def _js_reorder_mapping(mapping: Dict[Any, Any]) -> None:
    """Reorder a mapping's own keys in place when ECMAScript would differ."""
    keys = list(mapping.keys())
    ordered = _js_own_key_order(keys)
    if ordered != keys:
        items = [(key, mapping[key]) for key in ordered]
        mapping.clear()
        mapping.update(items)


def _js_read_key(value: Any, key: Any) -> Any:
    """``value[key]``, where a key the value does not have reads as ``undefined``."""
    if isinstance(value, dict):
        return value[key] if key in value else _UNDEFINED
    if isinstance(value, memoryview):
        if isinstance(key, str) and key.isdigit() and int(key) < len(value):
            return value[int(key)]
        return _UNDEFINED  # an index past the view's byteLength
    return getattr(value, key, _UNDEFINED)


def _fresh_date(value: Any) -> Any:
    """A new ``Date`` for the reference's ``new Date(source.valueOf())`` branch."""
    if isinstance(value, datetime.datetime):
        return datetime.datetime(
            value.year, value.month, value.day, value.hour, value.minute,
            value.second, value.microsecond, tzinfo=value.tzinfo, fold=value.fold,
        )
    return datetime.date(value.year, value.month, value.day)


def _fresh_pattern(value: Any) -> Any:
    """A new ``RegExp`` for the reference's ``new RegExp(source, flags)`` branch.

    ``re.compile`` hands back the interned pattern for a (source, flags) pair
    this process already compiled, so the compiler entry point below builds a
    distinct object instead. A ``RegExp`` clone also drops ``lastIndex``, of
    which Python keeps no state.
    """
    compiler = getattr(re, "_compiler", None)
    if compiler is not None:  # Python 3.11+ moves the compiler to `re._compiler`
        return compiler.compile(value.pattern, value.flags)
    import sre_compile
    return sre_compile.compile(value.pattern, value.flags)


def _leaf_copy_factory(value: Any) -> Optional[Callable[[], Any]]:
    """The fresh copy a reference leaf branch builds, or ``None`` for a container.

    Leaf branches: ``is('Date', ...)`` -> ``new Date``, ``is('RegExp', ...)`` ->
    ``new RegExp``, ``isArrayBufferLike`` -> ``source.slice(0)``, and
    ``ArrayBuffer.isView`` -> a copy of the view's own byte range.
    """
    if isinstance(value, (datetime.datetime, datetime.date)):
        return functools.partial(_fresh_date, value)
    if isinstance(value, _REGEX_TYPE):
        return functools.partial(_fresh_pattern, value)
    if isinstance(value, bytes):
        return lambda: bytes(bytearray(value))
    if isinstance(value, bytearray):
        return lambda: bytearray(value)
    if isinstance(value, memoryview):
        return value.tobytes
    return None


def _register_leaf_copies(value: Any, factories: Dict[int, Callable[[], Any]],
                          seen: Set[int]) -> None:
    """Register a fresh-copy factory for every leaf a clone can reach.

    The reference returns from its Date/RegExp/ArrayBuffer/ArrayBufferView
    branches *before* it consults ``refs``, so a leaf is copied once per
    occurrence while containers stay memoized. The walk reaches leaves through
    dict values, sequence and set elements, instance ``__dict__`` entries and
    ``__slots__``, the same places ``Reflect.ownKeys`` and array elements lead.
    """
    key = id(value)
    if key in seen:
        return
    seen.add(key)
    factory = _leaf_copy_factory(value)
    if factory is not None:
        factories[key] = factory
        return
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, _JS_FUNCTION_TYPES):
        return
    if isinstance(value, dict):
        for item in value.values():
            _register_leaf_copies(item, factories, seen)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _register_leaf_copies(item, factories, seen)
        return
    members: List[Any] = []
    own = getattr(value, "__dict__", None)
    if isinstance(own, dict):
        members.extend(own.values())
    for name in getattr(type(value), "__slots__", ()) or ():
        try:
            members.append(getattr(value, name))
        except AttributeError:
            pass
    for item in members:
        _register_leaf_copies(item, factories, seen)


class _CloneMemo(dict):
    """``copy.deepcopy`` memo carrying the reference's per-occurrence leaf copies.

    ``deepcopy`` reads ``memo.get(id(value))`` before it dispatches, so a
    registered leaf id answers with a new copy on every lookup and is never
    stored, while containers keep deepcopy's per-identity memo - the reference's
    ``refs`` map, which preserves shared containers and cycles.
    """

    def __init__(self) -> None:
        super().__init__()
        self.factories: Dict[int, Callable[[], Any]] = {}

    def get(self, key: Any, default: Any = None) -> Any:
        factory = self.factories.get(key)
        if factory is not None:
            return factory()
        return super().get(key, default)


def clone(value: Any) -> Any:
    """Deep clone a value matching Cosmokit clone.

    The reference re-creates containers with the source prototype and follows
    reference cycles, which is what ``copy.deepcopy`` does for Python values;
    each leaf branch builds a fresh instance per occurrence (see `_CloneMemo`).

    LEGAL_ADAPTATION: Python has no property enumerability, so a cloned object
    keeps the source's own attributes as plain ones, and values with no
    reference counterpart (an unchanged ``tuple``/``frozenset`` of atomic
    elements) may be shared with the source where the reference allocates.

    LEGAL_ADAPTATION: the reference's leaf/container branches cover arrays,
    dates, regexps, buffers and plain objects but not `Set`/`Map`/`WeakSet`/
    `WeakMap`/`Promise`: it rebuilds those from their prototype alone, which
    drops the internal slots, so ``clone(new Set([1]))`` yields an object whose
    every method throws. The port deep-copies those containers, and raises
    `TypeError` for a `Promise` (an `asyncio.Future`) whose state cannot be
    rebuilt; no caller in the tree clones any of them.
    """
    memo = _CloneMemo()
    _register_leaf_copies(value, memo.factories, set())
    result = copy.deepcopy(value, memo)
    # The reference assigns into each new object in `Reflect.ownKeys` order, so
    # every cloned object enumerates in ECMAScript own-key order; the reorder
    # is in place, which keeps shared containers and cycles shared.
    _js_reorder_clone_keys(result, set())
    return result


def _js_reorder_clone_keys(value: Any, seen: Set[int]) -> None:
    """Reorder a cloned value's own keys the way the reference enumerates them.

    See `_js_own_key_order`; the containers are reused, so container identity
    - what preserves aliasing and cycles in a clone - is unchanged.
    """
    key = id(value)
    if key in seen:
        return
    seen.add(key)
    if isinstance(value, dict):
        for item in list(value.values()):
            _js_reorder_clone_keys(item, seen)
        _js_reorder_mapping(value)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _js_reorder_clone_keys(item, seen)
        return
    own = getattr(value, "__dict__", None)
    if isinstance(own, dict):
        for item in list(own.values()):
            _js_reorder_clone_keys(item, seen)
        _js_reorder_mapping(own)
        return
    for name in getattr(type(value), "__slots__", ()) or ():
        try:
            item = getattr(value, name)
        except AttributeError:
            continue
        _js_reorder_clone_keys(item, seen)


def deep_equal(a: Any, b: Any, strict: bool = False) -> bool:
    """Deep equality check matching Cosmokit deepEqual."""
    # The opening reference test is `a === b`, not object identity: two equal
    # strings are distinct Python objects, so `is` would report them unequal
    # while `===` (and the reference) reports equal.
    if _js_strict_equal(a, b):
        return True
    if not strict and _js_is_nullish(a) and _js_is_nullish(b):
        return True
    if _js_typeof(a) != _js_typeof(b):
        return False
    if _js_typeof(a) != "object":
        return False  # non-object primitives that were not identical
    if _js_is_nullish(a) or _js_is_nullish(b):
        return False  # `if (!a || !b) return false`: null and undefined only
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            return False
        if len(a) != len(b):
            return False
        # `a.every((item, index) => deepEqual(item, b[index]))`: the array branch
        # does not forward `strict` to its elements.
        return all(deep_equal(x, y) for x, y in zip(a, b))
    if isinstance(a, (datetime.datetime, datetime.date)) or isinstance(b, (datetime.datetime, datetime.date)):
        if not (isinstance(a, (datetime.datetime, datetime.date))
                and isinstance(b, (datetime.datetime, datetime.date))):
            return False
        return a == b
    if isinstance(a, _REGEX_TYPE) or isinstance(b, _REGEX_TYPE):
        if not (isinstance(a, _REGEX_TYPE) and isinstance(b, _REGEX_TYPE)):
            return False
        return a.pattern == b.pattern and a.flags == b.flags
    # `check(isArrayBufferLike, ...)`: only buffers that own their memory take
    # this branch, so an ArrayBuffer never equals a TypedArray over the same
    # bytes - the view falls through to the own-index-key comparison below.
    if isinstance(a, (bytes, bytearray)) or isinstance(b, (bytes, bytearray)):
        if not (isinstance(a, (bytes, bytearray)) and isinstance(b, (bytes, bytearray))):
            return False
        return bytes(a) == bytes(b)
    # Reference fallback:
    # Object.keys({...a, ...b}).every(key => deepEqual(a[key], b[key], strict))
    keys: List[Any] = []
    for source in (a, b):
        for key in _js_own_enumerable_keys(source):
            if key not in keys:
                keys.append(key)
    return all(deep_equal(_js_read_key(a, key), _js_read_key(b, key), strict=strict) for key in keys)


deepEqual = deep_equal


def pick(obj: Dict[str, Any], keys: Optional[Any] = None, forced: bool = False) -> Dict[str, Any]:
    """Pick specified keys from a dictionary matching Cosmokit pick.

    misc.ts:52-60 is ``if (!keys) return { ...source }`` followed by
    ``if (forced || source[key] !== undefined) result[key] = source[key]``, so
    the port's ``undefined`` sentinel enters and leaves the result: a property
    that reads as ``undefined`` - an absent key, or one the source itself holds
    as ``undefined`` - is dropped unless ``forced`` keeps it, while a forced
    miss keeps the sentinel itself rather than Python's ``None``, which is the
    reference's ``null`` and is a value ``source[key] !== undefined`` keeps.
    LEGAL_ADAPTATION: `_js_read_key` is the port of ``source[key]`` and
    `_js_truthy` the port of the ``!keys`` short-circuit.
    """
    if not _js_truthy(keys):
        return _js_ordered_mapping(obj)
    res = {}
    for k in keys:
        value = _js_read_key(obj, k)
        if forced or value is not _UNDEFINED:
            res[k] = value
    # The reference's result is a fresh object whose enumeration order is
    # ECMAScript own-key order, whatever order the keys arrived in.
    _js_reorder_mapping(res)
    return res


def omit(obj: Dict[str, Any], keys: Optional[Any] = None) -> Dict[str, Any]:
    """Omit specified keys from a dictionary matching Cosmokit omit.

    misc.ts:62-69 is ``if (!keys) return { ...source }`` followed by a
    ``Reflect.deleteProperty`` per key, so a falsy key collection takes the
    shallow-copy branch - `_js_truthy` is the port of ``!keys``, exactly as in
    :func:`pick`.  An empty string is falsy there and copies, while an empty
    list, tuple or set is truthy there and deletes nothing.
    """
    if not _js_truthy(keys):
        return _js_ordered_mapping(obj)
    key_set = set(keys)
    return {k: v for k, v in _js_ordered_mapping(obj).items() if k not in key_set}


def _js_supplied_arg_count(callback: Callable[..., Any], maximum: int = 2) -> Optional[int]:
    """LEGAL_ADAPTATION: JavaScript ignores surplus arguments, Python cannot.

    Cosmokit always invokes these callbacks with a fixed argument list --
    ``filter(key, value)`` for filterKeys and ``transform(value, key)`` for
    mapValues.  JavaScript hands the surplus arguments to a callback declared
    with fewer parameters and reads the missing ones as ``undefined`` for one
    declared with more, so the closest Python equivalent is to supply exactly
    as many arguments as the callback declares positional slots for: fewer than
    the reference arity for a callback that ignores the surplus arguments (a
    callback with no positional slot is the ``() => ...`` equivalent and is
    called with no argument at all) and more - the surplus slots receive the
    port's ``undefined`` sentinel through ``_js_call_args`` - for a callback
    that declares them.  A declared surplus slot with a default is left to that
    default, exactly as JavaScript's ``undefined`` triggers it, so it is not
    padded.  A callback whose signature CPython cannot report (a C-implemented
    callable such as ``str`` or ``bool``) reports ``None`` instead, and the
    reference's own argument list is replayed by :func:`_js_call_callback`.
    """
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return None
    params = list(signature.parameters.values())
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return maximum
    positional = [
        p for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    # Required slots beyond the reference arity are read as `undefined` in
    # JavaScript, so the call must reach them; a trailing defaulted slot is
    # left to its default, which is what a JavaScript `undefined` does.
    required = 0
    for index, parameter in enumerate(positional):
        if parameter.default is inspect.Parameter.empty:
            required = index + 1
    return max(min(len(positional), maximum), required)


def _js_call_args(arguments: Tuple[Any, ...], count: int) -> Tuple[Any, ...]:
    """The reference's positional argument list, padded to ``count``.

    Slots the callback declares beyond the values the reference passes are
    read as ``undefined`` in JavaScript, so they are filled with the port's
    ``_UNDEFINED`` sentinel (see :func:`_js_supplied_arg_count`).
    """
    supplied = list(arguments[:count])
    supplied.extend([_UNDEFINED] * (count - len(supplied)))
    return tuple(supplied)


def _js_call_callback(callback: Callable[..., Any], arguments: Tuple[Any, ...], maximum: int = 2) -> Any:
    """Invoke a callback with the reference's positional argument list.

    The reference always passes the same two arguments - ``filter(key, value)``
    for filterKeys and ``transform(value, key)`` for mapValues - so this is the
    single adaptation point for JavaScript's argument rule:

    * a callback whose positional slots CPython can report is called with
      exactly those slots (see :func:`_js_supplied_arg_count` and
      :func:`_js_call_args`); a non-TypeError it raises propagates unchanged;
    * a C-implemented callable reports no signature, so its slots cannot be
      read and the reference's argument list is replayed from its full length
      down to none - the shortest list that binds wins, which is what
      "JavaScript drops the surplus arguments" means for such a callable (Node
      oracle: ``mapValues({a:1,b:2}, String)`` is ``{"a":"1","b":"2"}``).
      A non-TypeError propagates unchanged, and when every attempt raises
      TypeError the reference-faithful (longest) call is re-raised rather than
      a shortened binding failure, so a genuine error is never masked.
    """
    supplied = _js_supplied_arg_count(callback, maximum)
    if supplied is not None:
        return callback(*_js_call_args(arguments, supplied))
    first_error = None
    for count in range(min(maximum, len(arguments)), -1, -1):
        try:
            return callback(*arguments[:count])
        except TypeError as error:
            if first_error is None:
                first_error = error
    raise first_error


def filter_keys(obj: Dict[str, Any], predicate: Callable[..., bool]) -> Dict[str, Any]:
    """Filter dictionary keys matching Cosmokit filterKeys.

    The reference builds the result with
    ``Object.entries(object).filter(([key, value]) => filter(key, value))``, so
    the predicate result is tested with ECMAScript ``ToBoolean`` (``[]`` and
    ``{}`` keep the entry while ``NaN`` drops it) and the predicate always
    receives ``(key, value)``.
    """
    # LEGAL_ADAPTATION: the reference always calls `filter(key, value)` and
    # JavaScript silently ignores surplus arguments and fills the missing ones
    # with `undefined`; Python cannot express either, so the predicate arity
    # picks the equivalent call (see _js_call_callback, which pads through
    # _js_call_args and replays the reference list for an unreported one).
    res = {}
    # `Object.entries(object)` enumerates in ECMAScript own-key order, which
    # `Object.fromEntries` then preserves.
    for k in _js_own_enumerable_keys(obj):
        v = _js_read_key(obj, k)
        if _js_truthy(_js_call_callback(predicate, (k, v))):
            res[k] = v
    return res


filterKeys = filter_keys


def capitalize(source: str) -> str:
    """Uppercase the first character of a string (``source.charAt(0)``)."""
    return source[:1].upper() + source[1:]


def uncapitalize(source: str) -> str:
    """Lowercase the first character of a string (``source.charAt(0)``)."""
    return source[:1].lower() + source[1:]


def camel_case(source: str) -> str:
    """Convert dash or underscore delimited text to camelCase matching Cosmokit camelCase."""
    return re.sub(r"[_-]([a-z])", lambda m: m.group(1).upper(), source)


camelCase = camel_case
camelize = camel_case


class _TokenizeState:
    DELIM = 0
    UPPER = 1
    LOWER = 2


def _tokenize(source: str, delimiters: List[int], delimiter: int) -> str:
    output = []
    state = _TokenizeState.DELIM
    for i, ch in enumerate(source):
        code = ord(ch)
        if 65 <= code <= 90:
            if state == _TokenizeState.UPPER:
                next_code = ord(source[i + 1]) if i + 1 < len(source) else 0
                if 97 <= next_code <= 122:
                    output.append(delimiter)
                output.append(code + 32)
            else:
                if state != _TokenizeState.DELIM:
                    output.append(delimiter)
                output.append(code + 32)
            state = _TokenizeState.UPPER
        elif 97 <= code <= 122:
            output.append(code)
            state = _TokenizeState.LOWER
        elif code in delimiters:
            if state != _TokenizeState.DELIM:
                output.append(delimiter)
            state = _TokenizeState.DELIM
        else:
            output.append(code)
    return "".join(chr(c) for c in output)


def param_case(source: str) -> str:
    """Convert text to dash-delimited parameter case matching Cosmokit paramCase."""
    return _tokenize(source, [45, 95], 45)


paramCase = param_case
hyphenate = param_case


def snake_case(source: str) -> str:
    """Convert text to underscore-delimited snake_case matching Cosmokit snakeCase."""
    return _tokenize(source, [45, 95], 95)


snakeCase = snake_case


def template(source: str, params: Dict[str, Any]) -> str:
    """Interpolate {key} or {{key}} placeholders in a string.

    NOTE: this helper is not part of the cosmokit package contract - cosmokit's
    `template` is `Time.template(template, date)`, implemented above.  This is
    the harness prompt-variable interpolation helper kept here for the existing
    callers.
    """
    def _repl(match):
        k = match.group(1) or match.group(2)
        return str(params.get(k, match.group(0)))
    return re.sub(r"\{\{([^{}]+)\}\}|\{([^{}]+)\}", _repl, source)


class DisposableList(Generic[T]):
    """
    Ordered collection of disposable values with O(1) deletion by value.
    Matching reference/vendor/cordis/src/utils.ts DisposableList.
    """

    def __init__(self) -> None:
        self._sn = 0
        self._map: Dict[int, T] = {}
        self._id_to_sn: Dict[int, int] = {}

    @property
    def length(self) -> int:
        return len(self._map)

    def __len__(self) -> int:
        return len(self._map)

    def push(self, value: T) -> Callable[[], bool]:
        """Push a disposable item to the list and return disposer."""
        self._sn += 1
        sn = self._sn
        self._map[sn] = value
        self._id_to_sn[id(value)] = sn
        return lambda: self.delete_by_sn(sn)

    def unshift(self, value: T) -> Callable[[], bool]:
        """Insert at beginning matching TS DisposableList.unshift / events."""
        self._sn += 1
        sn = self._sn
        new_map = {sn: value}
        new_map.update(self._map)
        self._map = new_map
        self._id_to_sn[id(value)] = sn
        return lambda: self.delete_by_sn(sn)

    def delete_by_sn(self, sn: int) -> bool:
        if sn in self._map:
            val = self._map.pop(sn)
            self._id_to_sn.pop(id(val), None)
            return True
        return False

    def delete(self, value: T) -> bool:
        """Delete an item by identity, with bound method fallback."""
        val_id = id(value)
        if val_id in self._id_to_sn:
            sn = self._id_to_sn.pop(val_id)
            if sn in self._map:
                del self._map[sn]
                return True

        for sn, v in list(self._map.items()):
            if v is value:
                del self._map[sn]
                self._id_to_sn.pop(id(v), None)
                return True

        if inspect.ismethod(value):
            for sn, v in list(self._map.items()):
                if inspect.ismethod(v) and v.__self__ is value.__self__ and v.__func__ is value.__func__:
                    del self._map[sn]
                    self._id_to_sn.pop(id(v), None)
                    return True

        return False

    def clear(self) -> List[T]:
        """Clear all entries and return values in reverse registration order."""
        values = list(self._map.values())
        self._map.clear()
        self._id_to_sn.clear()
        values.reverse()
        return values

    def __iter__(self) -> Iterator[T]:
        return iter(list(self._map.values()))

    def __repr__(self) -> str:
        return f"DisposableList({list(self._map.values())})"


class Symbols:
    """
    Symbol constants matching reference/vendor/cordis/src/utils.ts.
    """
    # Internal symbols
    shadow = "cordis.shadow"
    receiver = "cordis.receiver"
    original = "cordis.original"
    metadata = "cordis.metadata"
    initHooks = "cordis.initHooks"
    checkProto = "cordis.checkProto"

    # Context symbols
    effect = "cordis.effect"
    filter = "cordis.filter"
    isolate = "cordis.isolate"
    intercept = "cordis.intercept"

    # Service symbols
    init = "cordis.init"
    check = "cordis.check"
    config = "cordis.config"
    invoke = "cordis.invoke"
    extend = "cordis.extend"
    tracker = "cordis.tracker"
    resolveConfig = "cordis.resolveConfig"
    resolve_config = "cordis.resolveConfig"
    init_hooks = "cordis.initHooks"


symbols = Symbols()


def is_object(value: Any) -> bool:
    """Return true for non-null objects and functions matching TS isObject."""
    if value is None:
        return False
    if isinstance(value, (int, float, str, bool, bytes, bytearray)):
        return False
    return True


def is_nullable(value: Any) -> bool:
    """Return true when value is `null` or `undefined` (misc.ts:20-21).

    The reference is `value === null || value === undefined`, and the port
    carries the two ECMAScript nullish values separately: Python ``None`` is
    the reference's ``null``, while ``_UNDEFINED`` is the port's own
    ``undefined`` sentinel (the value ``deepEqual`` reads for a key only one
    operand owns, and the value ``make_array``/``is_("Undefined", ...)`` must
    recognize).  ``_js_is_nullish`` answers for both, so `isNullable(None)` and
    `isNullable(undefined)` are both true.
    """
    return _js_is_nullish(value)


isNullable = is_nullable


def noop(*args: Any, **kwargs: Any) -> Any:
    """No-op callback matching Cosmokit noop.

    `misc.ts:17` is `export function noop(): any {}`, whose value is
    `undefined`, so the port returns its own ``undefined`` sentinel - the one
    value `is_("Undefined", ...)`, `clone` and `deepEqual` already read as the
    reference's `undefined` - rather than ``None``, which is the port's
    `null`.  The permissive signature is a calling-convention adaptation:
    every call site discards the value, and Python does not enforce arity.
    """
    return _UNDEFINED


def is_non_nullable(value: Any) -> bool:
    """Return true when value is neither `null` nor `undefined` (misc.ts:25-27).

    The reference is the negation of `isNullable`, so the port negates the
    same predicate instead of testing for ``None`` alone.
    """
    return not is_nullable(value)

isNonNullable = is_non_nullable


def is_plain_object(data: Any) -> Any:
    """Non-array object test matching Cosmokit isPlainObject.

    The reference is `data && typeof data === 'object' && !Array.isArray(data)`:
    every non-array object (date, regexp, map, set, class instance) counts as
    "plain", only primitives, functions and arrays are rejected. A tuple is the
    second Python sequence type, so it maps to the array bucket like
    `make_array`/`is_("Array", ...)`.

    The leading `data &&` is an ECMAScript short-circuit, so it returns the
    falsy operand itself instead of `false`: `isPlainObject(null)` is `null`,
    `isPlainObject(0)` is `0`, `isPlainObject(NaN)` is `NaN` and
    `isPlainObject(undefined)` is `undefined` (the Node oracle answers
    `isPlainObject(0) === 0`). Only truthy non-objects answer the boolean
    `false`, and the falsy set is ECMAScript's, so a Python value that is only
    falsy here (`[]`, `{}`, `()`, `set()`) stays on the object branch.

    RESIDUAL: because the operand comes back unchanged, the operand's Python
    truthiness is what a Python condition sees. `float('nan')` is the single
    JavaScript-falsy value Python calls truthy, so
    `bool(is_plain_object(float('nan')))` is true where `!!isPlainObject(NaN)`
    is false in the reference; no Python value is both a NaN and falsy.
    """
    if not _js_truthy(data):
        return data
    if _js_typeof(data) != "object":
        return False  # a primitive (typeof !== 'object') or a function
    if isinstance(data, (list, tuple)):
        return False  # Array.isArray
    # Every other object is accepted, including empty dicts/sets (a Python
    # empty container is falsy but the reference object is truthy).
    return True


isPlainObject = is_plain_object


#: `Date.prototype.toString` weekday and month names (the reference renders an
#: English date string regardless of the machine locale).
_JS_WEEKDAY_NAMES = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
_JS_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: JavaScript `RegExp` flag letters in the engine's canonical order (``d g i m
#: s u v y``) with the Python flag each stands for.  The other Python flags
#: (`re.A`, `re.L`, `re.U`, `re.X`) have no JavaScript flag letter, and a
#: JavaScript-only letter (`d`, `g`, `u`, `v`, `y`) has no Python flag - the
#: port's regexps are built by Python callers, so only the shared letters occur.
_JS_REGEX_FLAGS = (("i", re.IGNORECASE), ("m", re.MULTILINE), ("s", re.DOTALL))


def _js_date_to_string(value: datetime.datetime) -> str:
    """``Date.prototype.toString`` for the port's naive local `datetime`.

    A JavaScript `Date` is carried as the naive local `datetime` the port's
    epoch arithmetic produces, so the calendar fields are read directly while
    the offset and zone name come from the platform's current local state - the
    same source `Time.timezoneOffset` derives its constant from (the reference
    computes its own offset constant at module load too).

    LEGAL_ADAPTATION: a `datetime` covers years 1..9999 while a JavaScript
    `Date` covers a far wider range, and a zone observing DST reports its
    current state rather than the instant's; the zone name is the platform's
    localized name, which is what the reference's engine reports as well.
    """
    offset = _local_utc_offset_seconds()
    total = abs(int(offset))
    is_dst = bool(time.daylight) and bool(time.localtime().tm_isdst)
    return "%s %s %02d %04d %02d:%02d:%02d GMT%s%02d%02d (%s)" % (
        _JS_WEEKDAY_NAMES[(value.weekday() + 1) % 7], _JS_MONTH_NAMES[value.month - 1],
        value.day, value.year, value.hour, value.minute, value.second,
        "+" if offset >= 0 else "-", total // 3600, (total % 3600) // 60,
        time.tzname[1 if is_dst else 0],
    )


def _js_regex_to_string(value: Any) -> str:
    """``RegExp.prototype.toString``, i.e. ``/source/flags``."""
    flags = "".join(letter for letter, flag in _JS_REGEX_FLAGS if value.flags & flag)
    return "/{}/{}".format(value.pattern, flags)


def _js_error_to_string(value: BaseException) -> str:
    """``Error.prototype.toString``, i.e. ``name`` or ``name: message``.

    LEGAL_ADAPTATION: the reference reads the error's own `name` property,
    which its constructors initialise to the native error name.  The closest
    Python equivalent is the exception class name, so a Python error with no
    JavaScript native namesake renders under its own name.
    """
    name = type(value).__name__
    message = str(value)
    if not name:
        return message
    if not message:
        return name
    return "{}: {}".format(name, message)


def _js_to_string_element(value: Any) -> str:
    """``ToString`` for one element of ``Array.prototype.join``."""
    if _js_is_nullish(value):
        return ""  # join renders a nullish element as the empty string
    return _js_key_to_string(value)


def _js_array_to_string(value: Any) -> str:
    """``Array.prototype.toString``, which is ``join(',')``."""
    return ",".join(_js_to_string_element(item) for item in value)


def _js_key_to_string(key: Any) -> str:
    """The reference's ``key.toString()`` for a non-string `formatProperty` key.

    `formatProperty` wraps a non-string key with ``key.toString()``, so every
    non-string value renders through its own prototype's string conversion: a
    number through `Number.prototype.toString`, an array (and a typed array,
    whose `toString` is the shared `Array.prototype.toString`) through
    ``join(',')``, a `Date` through `Date.prototype.toString`, a `RegExp`
    through `RegExp.prototype.toString`, an `Error` through
    `Error.prototype.toString`, and an ordinary object through
    `Object.prototype.toString`.  A nullish key has no `toString` at all and
    throws.

    LEGAL_ADAPTATION: the package's declared key domain is ``keyof any``
    (``string | number | symbol``), and the port carries a JavaScript symbol as
    a Python string (see `Symbols`), so a symbol key formats through the string
    branch instead of `Symbol.prototype.toString`.  `Function.prototype.toString`
    returns a function's source text, which Python does not keep, so a function
    key renders as its internal `Object.prototype.toString` tag.  An object that
    carries a `toString` of its own has no counterpart either: a JavaScript
    object literal is a `dict` here and a JavaScript method has no property to
    hang on, so every ordinary object renders through
    `Object.prototype.toString`.  A `memoryview` stands for a typed array and
    for `DataView` alike; Python exposes one generic view type, so every view
    renders through the typed-array form, exactly as `is_` maps them to one
    type.
    """
    if key is None or key is _UNDEFINED:
        # `null.toString()` / `undefined.toString()` throw a TypeError.
        noun = "null" if key is None else "undefined"
        raise TypeError("Cannot read properties of {} (reading 'toString')".format(noun))
    if isinstance(key, str):
        return key
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, (int, float)):
        return _js_number_to_string(key)
    if isinstance(key, (list, tuple, memoryview)):
        return _js_array_to_string(key)
    if isinstance(key, datetime.datetime):
        return _js_date_to_string(key)
    if isinstance(key, _REGEX_TYPE) and isinstance(key.pattern, str):
        return _js_regex_to_string(key)
    if isinstance(key, BaseException):
        return _js_error_to_string(key)
    if isinstance(key, (set, frozenset)):
        return "[object Set]"
    if isinstance(key, (bytes, bytearray)):
        # The port carries an ArrayBuffer (and the Buffer `Binary` reads) as
        # bytes/bytearray, whose `Object.prototype.toString` tag this is.
        return "[object ArrayBuffer]"
    if isinstance(key, weakref.WeakSet):
        return "[object WeakSet]"
    if isinstance(key, weakref.WeakKeyDictionary):
        return "[object WeakMap]"
    if isinstance(key, _JS_FUNCTION_TYPES):
        return "[object Function]"
    return "[object Object]"


def format_property(key: Any) -> str:
    """Format a property key as a JavaScript member access suffix matching Cosmokit formatProperty."""
    import json
    if not isinstance(key, str):
        # `[${key.toString()}]` - the key's own JavaScript string conversion.
        return "[{}]".format(_js_key_to_string(key))
    # The reference uses /^[a-z_$][\w$]*$/i without the /u flag, so `\w` is
    # ASCII-only; Python's `re` is Unicode-aware by default.  ECMAScript `$`
    # (without the `m` flag) only matches at the very end of the input while
    # Python's also matches just before a trailing newline, so this literal
    # anchors with `\Z`: `formatProperty("foo\n")` is `["foo\n"]`, not a
    # member access, exactly as the reference answers.
    if re.match(r"^[a-zA-Z_$][0-9A-Za-z_$]*\Z", key):
        return f".{key}"
    return f"[{json.dumps(key, ensure_ascii=False)}]"


formatProperty = format_property


def trim_slash(source: str) -> str:
    """Remove one trailing slash from a path string matching Cosmokit trimSlash."""
    if source.endswith("/"):
        return source[:-1]
    return source


trimSlash = trim_slash


def sanitize(source: str) -> str:
    """Ensure a path starts with '/' and has no trailing slash matching Cosmokit sanitize."""
    if not source.startswith("/"):
        source = "/" + source
    return trim_slash(source)


def _js_membership_set(array: Any) -> Dict[Any, bool]:
    """SameValueZero membership set backing ``Array.prototype.includes``."""
    keys: Dict[Any, bool] = {}
    for item in array:
        keys[_js_membership_key(item)] = True
    return keys


def _js_set_element(value: Any) -> Any:
    """The value a JavaScript ``Set`` stores for ``value``.

    ECMA-262 ``Set.prototype.add`` stores ``-0`` as ``+0`` (the same
    normalization ``Map`` keys get), so the two helpers that build their result
    through a Set - `union` and `deduplicate` - answer with a positive zero
    where the ``filter``/``indexOf`` helpers keep the operand unchanged.
    """
    if isinstance(value, float) and value == 0:
        return 0.0
    return value


def contain(array1: Any, array2: Any) -> bool:
    """Return true when every item in array2 is present in array1.

    ``array1.includes(item)`` uses SameValueZero, not Python ``==``.
    """
    keys = _js_membership_set(array1)
    return all(_js_membership_key(item) in keys for item in array2)


def intersection(array1: Any, array2: Any) -> List[Any]:
    """Return items that appear in both arrays (``includes`` semantics)."""
    keys = _js_membership_set(array2)
    return [item for item in array1 if _js_membership_key(item) in keys]


def difference(array1: Any, array2: Any) -> List[Any]:
    """Return items from array1 that do not appear in array2 (``includes`` semantics)."""
    keys = _js_membership_set(array2)
    return [item for item in array1 if _js_membership_key(item) not in keys]


def union(array1: Any, array2: Any) -> List[Any]:
    """Return the set-union of two arrays while preserving first occurrence order.

    The result is built through a JavaScript ``Set``, whose elements are
    normalized by :func:`_js_set_element`.
    """
    res = []
    seen: Dict[Any, bool] = {}
    for item in list(array1) + list(array2):
        key = _js_membership_key(item)
        if key in seen:
            continue
        seen[key] = True
        res.append(_js_set_element(item))
    return res


def deduplicate(array: Any) -> List[Any]:
    """Remove duplicate values while preserving first occurrence order.

    The result is built through a JavaScript ``Set``, whose elements are
    normalized by :func:`_js_set_element`.
    """
    res = []
    seen: Dict[Any, bool] = {}
    for item in array:
        key = _js_membership_key(item)
        if key in seen:
            continue
        seen[key] = True
        res.append(_js_set_element(item))
    return res


def remove(lst: List[Any], item: Any) -> bool:
    """Remove one item from a list and report whether it was found.

    ``list?.indexOf(item)`` uses strict equality (``===``) and tolerates a
    nullish list - `null` and the port's ``undefined`` sentinel alike, since
    optional chaining short-circuits on both.
    """
    if _js_is_nullish(lst):
        return False
    for index, value in enumerate(lst):
        if _js_strict_equal(value, item):
            del lst[index]
            return True
    return False


def make_array(source: Any) -> List[Any]:
    """Normalize nullish, scalar, or array input to a list.

    LEGAL_ADAPTATION: Python's `tuple` is the second array-like sequence type
    (there is no second ECMAScript array type), so it is treated like `list` -
    the same mapping `is_("Array", ...)` uses.  A `set` is not an array in the
    reference either, so it is wrapped as a scalar value.
    """
    if _js_is_nullish(source):
        return []
    if isinstance(source, list):
        return source
    if isinstance(source, tuple):
        return list(source)
    return [source]


makeArray = make_array


class Time:
    """Time constants and parsing helpers matching Cosmokit Time."""
    millisecond = 1
    second = 1000
    minute = second * 60
    hour = minute * 60
    day = hour * 24
    week = day * 7

    #: `new Date().getTimezoneOffset()`: minutes west of UTC in the local DST
    #: state. Derived from `time.timezone`/`time.altzone`, which a Windows build
    #: always provides, instead of `struct_time.tm_gmtoff`, which it may omit - a
    #: missing field must not silently default the offset to UTC.
    _timezone_offset = -int(_local_utc_offset_seconds() / 60)

    @classmethod
    def set_timezone_offset(cls, offset: int) -> None:
        cls._timezone_offset = offset

    setTimezoneOffset = set_timezone_offset

    @classmethod
    def get_timezone_offset(cls) -> int:
        return cls._timezone_offset

    getTimezoneOffset = get_timezone_offset

    @classmethod
    def get_date_number(cls, date: Optional[Any] = None, offset: Optional[int] = None) -> int:
        """Convert a date to a day number matching Cosmokit Time.getDateNumber."""
        if date is None:
            date = datetime.datetime.now()
        elif isinstance(date, (int, float)) and not isinstance(date, bool):
            date = _datetime_from_epoch(date / 1000.0)
        if offset is None:
            offset = cls._timezone_offset
        ts_ms = _epoch_seconds_of(date) * 1000.0
        return int(math.floor((ts_ms / cls.minute - offset) / 1440))

    getDateNumber = get_date_number

    @classmethod
    def from_date_number(cls, value: int, offset: Optional[int] = None) -> datetime.datetime:
        """Convert a day number to a date matching Cosmokit Time.fromDateNumber.

        LEGAL_ADAPTATION: the reference is ``new Date(value * day + offset *
        minute)``, which answers a Date (or an Invalid Date past +/-8.64e15 ms)
        for every input, while this port carries a Date as a naive local
        `datetime` (years 1-9999), so a day number naming an instant outside
        that range raises instead of answering an unrepresentable value. The
        practical domain - day numbers for representable dates - round trips
        exactly, as `getDateNumber` does.
        """
        if offset is None:
            offset = cls._timezone_offset
        ts_ms = value * cls.day + offset * cls.minute
        return _datetime_from_epoch(ts_ms / 1000.0)

    fromDateNumber = from_date_number

    # ECMAScript regular expressions do not treat `$` as matching before a
    # trailing newline and `\d` is ASCII-only, so the reference parse-time
    # pattern is reproduced with `\Z` + re.ASCII.
    _TIME_REGEX = re.compile(
        r"^(?:(\d+(?:\.\d+)?)w(?:eek(?:s)?)?)?"
        r"(?:(\d+(?:\.\d+)?)d(?:ay(?:s)?)?)?"
        r"(?:(\d+(?:\.\d+)?)h(?:our(?:s)?)?)?"
        r"(?:(\d+(?:\.\d+)?)m(?:in(?:ute)?(?:s)?)?)?"
        r"(?:(\d+(?:\.\d+)?)s(?:ec(?:ond)?(?:s)?)?)?\Z",
        re.ASCII,
    )

    # JavaScript's `$` (without the `m` flag) only matches at the very end,
    # while Python's also matches before a trailing newline, so the mirrored
    # literals anchor with `\Z`.
    _TIME_ONLY_REGEX = re.compile(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\Z", re.ASCII)
    _MONTH_DAY_REGEX = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\Z", re.ASCII)
    # The Date Time String Format of ECMA-262: the month and day parts,
    # and the whole time part, are optional and default to 01/01/00:00:00;
    # a date-only form is UTC while a date-time form is local wall clock.
    _ISO_DATETIME_REGEX = re.compile(
        r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?"
        r"(?:(?:[Tt]|[ \t]+)(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?"
        r"(Z|z|[+-]\d{2}:?\d{2})?\Z",
        re.ASCII,
    )
    # Everything below reproduces V8's non-ISO grammar: `new Date(string)`
    # after the Date Time String Format fails, as the pinned Node 22 runtime
    # implements it (every table and rule here was derived by differential
    # probing of the vendored TypeScript).  A word names a month when it
    # starts with the three-letter month name (`Jan`, `Janx` and `January`
    # all name January, while `Ja` names nothing and `Ju` is ambiguous
    # between June and July); a timezone word must match exactly.
    _V8_MONTH_PREFIXES = ("jan", "feb", "mar", "apr", "may", "jun", "jul",
                          "aug", "sep", "oct", "nov", "dec")
    #: Timezone words V8 recognizes, in minutes east of UTC.  Any other
    #: abbreviation (`CET`, `BST`, `JST`, ...) is an ordinary word to V8.
    _V8_TIMEZONE_WORDS = {
        "ut": 0, "utc": 0, "gmt": 0, "z": 0, "est": -300, "edt": -240,
        "cst": -360, "cdt": -300, "mst": -420, "mdt": -360, "pst": -480,
        "pdt": -420,
    }
    #: Symbols V8 skips between tokens.  A colon is skipped as well, which is
    #: how `new Date("2026:3:5")` reads a clock time after the year, and every
    #: other character opens an unknown word (`_v8_word_symbol`).
    _V8_SKIPPED_SYMBOLS = frozenset(" !\"#$%&'*,-./;<=>?@:")
    _ASCII_DIGITS = "0123456789"
    _ASCII_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    _ASCII_WHITESPACE = " \t\n\r\f\v"

    @classmethod
    def parse_time(cls, source: str) -> float:
        """Parse time strings matching Cosmokit Time.parseTime."""
        if not source or not isinstance(source, str):
            return 0.0
        m = cls._TIME_REGEX.match(source)
        if not m or not m.group(0):
            return 0.0
        total = 0.0
        multipliers = [cls.week, cls.day, cls.hour, cls.minute, cls.second]
        for i, mult in enumerate(multipliers):
            g = m.group(i + 1)
            if g:
                total += float(g) * mult
        return total

    parseTime = parse_time

    @staticmethod
    def _is_valid_clock(hour: int, minute: int, second: int) -> bool:
        """V8 accepts 00:00-24:00:00 and rejects out-of-range clock parts."""
        if not (0 <= minute <= 59 and 0 <= second <= 59 and 0 <= hour <= 24):
            return False
        if hour == 24 and (minute != 0 or second != 0):
            return False
        return True

    @classmethod
    def parse_date(cls, date_str: str) -> datetime.datetime:
        """Parse date matching Cosmokit Time.parseDate.

        LEGAL_ADAPTATION: an ECMAScript ``Invalid Date`` has no Python value.
        Where the reference returns ``new Date(NaN)`` (an unreachable clock
        part, an out-of-range month/day or a string neither reader accepts)
        this port returns ``new Date()`` - the same value the reference uses
        for an empty input - instead of raising, keeping the no-throw
        contract of the reference.
        """
        parsed = cls.parse_time(date_str)
        now = datetime.datetime.now()
        if parsed:
            # The reference is `Date.now() + parsed`, a number the Date
            # constructor turns into a valid Date up to +/-8.64e15 ms and into
            # an Invalid Date past it.  `datetime` spans years 1-9999, so an
            # offset that far from `now` has no Python value and reports as
            # `new Date()` like every other unrepresentable instant
            # (`new Date("100000000000h")` is Invalid, `new Date("999999999999s")`
            # is a valid year-33715 Date; both land here).
            try:
                return now + datetime.timedelta(milliseconds=parsed)
            except (OverflowError, ValueError):
                return now
        # The reference rewrites a clock time with today's date and an
        # `M-D-HH:MM` string with the current year, then re-parses the joined
        # string, so the port joins the same string and reads it with the same
        # reader.  `new Date().toLocaleDateString()` is `M/D/YYYY` in the
        # `en-US` locale the reference runs on.
        if isinstance(date_str, str):
            if cls._TIME_ONLY_REGEX.match(date_str):
                date_str = "%d/%d/%d-%s" % (now.month, now.day, now.year, date_str)
            elif cls._MONTH_DAY_REGEX.match(date_str):
                date_str = "%d-%s" % (now.year, date_str)
        if not date_str:
            return now
        return cls._parse_js_date_string(date_str, now)

    parseDate = parse_date

    @staticmethod
    def _build_local(year: int, month: int, day: int, hour: int, minute: int,
                     second: int, microsecond: int) -> Optional[datetime.datetime]:
        """Build a local wall-clock instant; None when `datetime` cannot hold it.

        LEGAL_ADAPTATION: a `Date` spans about +/-8.64e15 ms while `datetime`
        spans years 1-9999, so only the reference values outside that range
        report as unrepresentable and fall back to `new Date()` like an
        unparseable string. `day` may exceed the month length: the reference
        normalizes "2026-02-30" to March 2 the same way `timedelta` does.
        """
        if not 1 <= year <= 9999:
            return None
        try:
            return (datetime.datetime(year, month, 1)
                    + datetime.timedelta(days=day - 1, hours=hour, minutes=minute,
                                         seconds=second, microseconds=microsecond))
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _build_zoned(year: int, month: int, day: int, hour: int, minute: int,
                     second: int, microsecond: int, offset_minutes: int) -> Optional[datetime.datetime]:
        """The local instant a wall-clock reading with `offset_minutes` east of
        UTC names, or None when `datetime` cannot hold it."""
        epoch = (calendar.timegm((year, month, 1, hour, minute, second))
                 + (day - 1) * 86400 - offset_minutes * 60)
        try:
            # The sub-second part is added after the conversion: a float epoch
            # loses a millisecond of a `Date`'s precision.
            return (_datetime_from_epoch(epoch)
                    + datetime.timedelta(microseconds=microsecond))
        except (OSError, OverflowError, ValueError):
            return None

    @staticmethod
    def _parse_zone_offset(offset: str) -> Optional[int]:
        """Zone offset in minutes, or None for an offset the reference rejects.

        ECMA-262 allows ``Z``/``z`` or ``+HH:MM``/``+HHMM`` with hours 00-23
        and minutes 00-59; every other offset is an Invalid Date in V8
        (``+24:00``, ``+00:60``, ``+02``, ``+02:00:00``).
        """
        if offset in ("Z", "z"):
            return 0
        digits = offset[1:].replace(":", "")
        hour, minute = int(digits[:2]), int(digits[2:])
        if hour > 23 or minute > 59:
            return None
        return (1 if offset[0] == "+" else -1) * (hour * 60 + minute)

    @classmethod
    def _parse_js_date_string(cls, source: Any, now: datetime.datetime) -> datetime.datetime:
        """`new Date(string)` for a date string, else `new Date()` (now).

        The Date Time String Format of ECMA-262 is read first - a date-only
        form is UTC, a date-time form is local wall clock unless it names an
        offset - and V8's non-ISO grammar (`_v8_parse_legacy`) second, in the
        same order the reference tries them.

        LEGAL_ADAPTATION: an unparseable string produces an Invalid Date that
        Python cannot represent, so a string neither reader accepts falls back
        to `new Date()` exactly like an empty string does; `now` is also what
        the port renders a reference Invalid Date as.  Two reference values are
        outside a naive local `datetime` and report as `now` as well: an
        instant past year 9999 / before year 1, and the local mean time V8's
        timezone data uses before a zone's first recorded offset (this port
        reads the current offset for every year, because neither the Windows 7
        timezone database nor Python's standard library carries historical
        offsets).
        """
        if not source or not isinstance(source, str):
            return now
        m = cls._ISO_DATETIME_REGEX.match(source)
        if m:
            year = int(m.group(1))
            # An absent month/day part defaults to the first of its parent.
            month = int(m.group(2)) if m.group(2) is not None else 1
            day = int(m.group(3)) if m.group(3) is not None else 1
            if not (1 <= month <= 12 and 1 <= day <= 31):
                return now
            if not 1 <= year <= 9999:
                # Representative in the reference, outside `datetime`.
                return now
            if m.group(4) is None:
                # A date-only form is UTC; a numeric offset needs a time part.
                if m.group(8) not in (None, "Z", "z"):
                    return now
                epoch = calendar.timegm((year, month, 1, 0, 0, 0)) + (day - 1) * 86400
                try:
                    return _datetime_from_epoch(epoch)
                except (OSError, OverflowError, ValueError):
                    return now
            hour, minute, second = int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)
            if not cls._is_valid_clock(hour, minute, second):
                return now
            # Date time values have millisecond resolution: extra digits truncate.
            micro = int((m.group(7) + "000")[:3]) * 1000 if m.group(7) else 0
            offset = m.group(8)
            if offset is None:
                # A date-time without an offset is local wall-clock time.
                return cls._build_local(year, month, day, hour, minute, second, micro) or now
            offset_minutes = cls._parse_zone_offset(offset)
            if offset_minutes is None:
                # An offset outside 00-23:00-59 is an Invalid Date.
                return now
            return cls._build_zoned(year, month, day, hour, minute, second, micro,
                                    offset_minutes) or now
        legacy = cls._v8_parse_legacy(source)
        return legacy if legacy is not None else now

    @classmethod
    def _v8_scan_offset(cls, source: str, start: int) -> Optional[Tuple[int, int, int]]:
        """V8's numeric zone offset at `start`, as (minutes east, value, end).

        The sign must be followed by digits and at most four of them open the
        offset (`GMT+12345` is not a token at all).  One or two digits are
        whole hours, a longer number splits into hours and minutes at its last
        two digits, and a `:MM` part holds at most two digits - a longer one
        is not part of the offset, so the reference reads it as a number
        (`12:30+12:345` is +12:00 with a stray 345).  `value` is the digit run
        itself, which V8 reads as a number when the offset leads the string
        (`new Date("GMT+0200")` is the year 200, not a timezone).
        """
        index = start + 1
        begin = index
        while index < len(source) and source[index] in cls._ASCII_DIGITS:
            index += 1
        digits = source[begin:index]
        if not digits or len(digits) > 4:
            return None
        value = int(digits)
        if index < len(source) and source[index] == ":":
            colon = index + 1
            end = colon
            while end < len(source) and end - colon < 2 and source[end] in cls._ASCII_DIGITS:
                end += 1
            if end == colon:
                return None
            hours, minutes, index = value, int(source[colon:end]), end
        elif len(digits) <= 2:
            hours, minutes = value, 0
        else:
            hours, minutes = int(digits[:-2]), int(digits[-2:])
        offset = hours * 60 + minutes
        return (offset if source[start] == "+" else -offset), value, index

    @classmethod
    def _v8_scan_time(cls, source: str, start: int) -> Optional[Tuple[Any, int]]:
        """V8's `H:M[:S[.ms]]` clock token at `start`, or None when the string
        is not a valid date at all.

        An hour past 24 is not a clock time (`new Date("99:00")` is Invalid
        rather than the year 99), a fraction that names no digit and a
        fraction on a clock time without seconds are Invalid (`12:30.` and
        `12:30.45`), and a minute or second past 59 is Invalid when another
        clock part follows while a final one leaves the run to the next token
        (`new Date("12:99:1")` is Invalid but `new Date("12:3456")` is the year
        3456 at 12:00).
        """
        digits = cls._ASCII_DIGITS
        length = len(source)
        index = start
        while index < length and source[index] in digits:
            index += 1
        if int(source[start:index]) > 24:
            return None
        values = [int(source[start:index])]
        seconds_read = False
        while len(values) < 3 and index < length and source[index] == ":":
            colon = index
            index += 1
            begin = index
            while index < length and source[index] in digits:
                index += 1
            if index == begin:
                # `12:` names 12:00:00, the same reading as a missing part.
                values.append(0)
                if len(values) == 3:
                    break
                continue
            value = int(source[begin:index])
            if value > 59:
                if index < length and source[index] == ":" and index + 1 < length \
                        and source[index + 1] in digits:
                    # A part past 59 that another clock part follows is not a
                    # clock time at all (`new Date("12:99:1")` is Invalid).
                    return None
                # As the last part it is not a clock part either: V8 leaves the
                # colon for the next token, which reads the run as a number
                # (`new Date("12:3456")` is the year 3456 at 12:00).
                index = colon
                break
            values.append(value)
            seconds_read = len(values) == 3
        micro = 0
        fraction_read = False
        if index < length and source[index] == ".":
            if not seconds_read:
                return None
            while index < length and source[index] == ".":
                begin = index + 1
                probe = begin
                while probe < length and source[probe] in digits:
                    probe += 1
                if probe == begin:
                    return None
                if not fraction_read:
                    micro = int((source[begin:probe] + "000")[:3]) * 1000
                fraction_read = True
                index = probe
        elif (index < length and source[index] not in cls._ASCII_WHITESPACE
              and source[index] not in ":+-Zz"):
            # Without a millisecond fraction V8 ends the clock token only at a
            # separator it recognizes: `new Date("Mar 5 2026 12:30/")` and
            # `new Date("Mar 5 2026 12:30PM")` are Invalid, while `12:30Z`,
            # `12:30+0200` and `12:30 ` are not.
            return None
        hour, minute = values[0], values[1] if len(values) > 1 else 0
        second = values[2] if len(values) > 2 else 0
        return (hour, minute, second, micro), index

    @classmethod
    def _v8_legacy_tokens(cls, source: str) -> Optional[List[Tuple[str, Any]]]:
        """V8's tokens for a non-ISO date string, or None when it rejects it.

        Tokens are `("num", value)`, `("clock", (hour, minute, second,
        micro))`, `("word", text)` and `("zone", minutes east of UTC)`.  A
        `+`/`-` is a sign only where it opens a token: between two numbers it
        is a separator, and after a clock time or a timezone word it opens a
        numeric offset instead.
        """
        tokens = []  # type: List[Tuple[str, Any]]
        index = 0
        length = len(source)
        while index < length:
            char = source[index]
            if char in cls._ASCII_WHITESPACE:
                index += 1
                continue
            if char == "(":
                # A parenthesized comment is skipped whole, nested parentheses
                # included; an unterminated one runs to the end, as in
                # `new Date("Mar 5 2026 (x")`.
                depth = 1
                index += 1
                while index < length and depth:
                    if source[index] == "(":
                        depth += 1
                    elif source[index] == ")":
                        depth -= 1
                    index += 1
                continue
            if char in "+-":
                trailing = tokens[-1][0] if tokens else None
                if trailing in ("clock", "zone", "marker"):
                    offset = cls._v8_scan_offset(source, index)
                    if offset is None:
                        return None
                    minutes, value, index = offset
                    if trailing == "zone":
                        has_field = any(t[0] in ("num", "clock") for t in tokens)
                        if (tokens[-1][1] and has_field
                                and not any(t[0] == "clock" for t in tokens)):
                            # Only the zero zones (`GMT`, `UT`, `UTC`, `Z`)
                            # may carry an offset without a clock time:
                            # `new Date("Mar 5 2026 EST+0200")` is invalid.
                            return None
                        if has_field:
                            tokens[-1] = ("zone", minutes)
                        else:
                            # A leading `GMT+0200` names the year 200 rather
                            # than a timezone: `new Date("GMT+0200")` is
                            # 0200-01-01, not an instant at 02:00.
                            tokens[-1] = ("num", value)
                    else:
                        tokens.append(("zone", minutes))
                    continue
                if char == "-" and index > 0 and (
                        source[index - 1] in cls._ASCII_DIGITS
                        or source[index - 1] in cls._ASCII_LETTERS
                        or source[index - 1] == "."):
                    # A hyphen attached to a number or a word is a separator
                    # (`new Date("5-Jan-2026")` names the 5th of January, and
                    # `new Date("5.-3")` names May 3), while a plus opens a
                    # sign wherever it appears.
                    index += 1
                    continue
                if any(token[0] in ("num", "clock") for token in tokens):
                    # A sign is legal only in the leading position: V8 rejects
                    # `new Date("1 -2")` and `new Date("Mar 5 2026 +")`.
                    return None
                index += 1
                continue
            if char in cls._ASCII_DIGITS:
                start = index
                while index < length and source[index] in cls._ASCII_DIGITS:
                    index += 1
                if (index < length and source[index] == ":" and index - start == 4
                        and any(token[0] in ("num", "clock") for token in tokens)):
                    # A four-digit year-like number carries a colon only where
                    # it leads the string: `new Date("2026:1")` names the first
                    # of January 2026 while `new Date("Mar 5 2026:")` is
                    # Invalid.
                    return None
                if index < length and source[index] == ":" and index - start != 4:
                    # A colon is only ignored after a four-digit year-like
                    # number (`new Date("2026:1")` names the first of January
                    # 2026); anywhere else it must open a clock time, and a
                    # string that does not open one is Invalid.
                    scanned = cls._v8_scan_time(source, start)
                    if scanned is None:
                        return None
                    clock, index = scanned
                    tokens.append(("clock", clock))
                    if (index < length and source[index] in "Zz"
                            and not (index + 1 < length
                                     and source[index + 1] in cls._ASCII_LETTERS)):
                        # `Z` glued to a clock is its UTC zone, and a number
                        # may follow it (`new Date("12:30:45.6z2026")` is the
                        # year 2026 at 20:30:45.600).
                        tokens.append(("zone", 0))
                        index += 1
                    continue
                tokens.append(("num", int(source[start:index])))
                continue
            if cls._v8_word_char(char):
                start = index
                while index < length and cls._v8_word_char(source[index]):
                    index += 1
                word = source[start:index]
                lowered = word.lower()
                if lowered in ("am", "pm") and any(t[0] == "clock" for t in tokens):
                    # A clock marker may carry a glued number
                    # (`new Date("12:30 PM5")` is May 2001 at 12:30).
                    tokens.append(("marker", lowered))
                    continue
                is_month = len(lowered) >= 3 and lowered[:3] in cls._V8_MONTH_PREFIXES
                if (not is_month and index < length
                        and source[index] in cls._ASCII_DIGITS
                        and not any(t[0] in ("num", "clock") for t in tokens)):
                    # A digit glued to a leading word that is not a month is
                    # not a number V8 reads: `new Date("Mar5")` is March 5
                    # while `new Date("GMT5")` and `new Date("x5")` are
                    # Invalid, but `new Date("1Z2")` reads the zone and the 2.
                    return None
                zone_word = cls._V8_TIMEZONE_WORDS.get(lowered)
                if zone_word is not None and cls._v8_zone_delimited(source, index):
                    tokens.append(("zone", zone_word))
                    continue
                tokens.append(("word", word))
                continue
            if char in cls._V8_SKIPPED_SYMBOLS:
                index += 1
                continue
            if char == ")":
                # A closing parenthesis is a token of its own: V8 ignores it
                # before the date and rejects `new Date("Mar 5 2026 )")`.
                tokens.append(("word", char))
                index += 1
                continue
            return None
        return tokens

    @staticmethod
    def _v8_word_char(char: str) -> bool:
        """True for a character V8 scans as part of a word.

        A word spans letters and every character outside V8's separator set,
        so `new Date("Mar~ 5 2026")` names March 5 and `new Date("a_G&4")`
        names April 2001.  Digits, whitespace, the skipped separators, `+`/`-`
        and the parentheses end the word.
        """
        if char in Time._ASCII_WHITESPACE or char in Time._ASCII_DIGITS:
            return False
        if char in Time._ASCII_LETTERS or char > "\x7f":
            return True
        return char not in Time._V8_SKIPPED_SYMBOLS and char not in "()+-"

    @classmethod
    def _v8_zone_delimited(cls, source: str, index: int) -> bool:
        """True when a timezone word ending at `index` is followed by a
        delimiter V8 accepts there: whitespace, `+`/`-`, a glued number, the
        end of the string, or nothing but skipped separators and comments
        (`new Date("GMT/50")` names January 1950 at 00:00, not a timezone)."""
        if index < len(source) and (source[index] in cls._ASCII_WHITESPACE
                                    or source[index] in "+-"
                                    or source[index] in cls._ASCII_DIGITS):
            # A glued number is read after the zone in `new Date("1Z2")`; a
            # leading one is not a token at all and is rejected before this.
            return True
        while index < len(source):
            if source[index] == "(":
                depth = 1
                index += 1
                while index < len(source) and depth:
                    if source[index] == "(":
                        depth += 1
                    elif source[index] == ")":
                        depth -= 1
                    index += 1
                continue
            if source[index] not in cls._V8_SKIPPED_SYMBOLS:
                return False
            index += 1
        return True

    @classmethod
    def _v8_parse_legacy(cls, source: str) -> Optional[datetime.datetime]:
        """V8's non-ISO `new Date(string)` reading, or None for an Invalid Date.

        The numbers name fields positionally - `month`, `day`, `year` unless a
        month name already filled the month, in which case `day`, `year` - a
        leading 0 or a leading number past 31 is the year instead, at most
        three numbers are read (an extra one is ignored), and a missing year
        is 2001, a missing day is 1.  A two-digit year takes the century V8
        gives it (0-49 is 20xx, 50-99 is 19xx).  The rest of the reading is
        `_v8_legacy_tokens` and `_v8_scan_time`: a clock time is local wall
        clock unless a timezone names an offset, and a month or day outside
        its range is an Invalid Date (a day past the month's length rolls
        forward, as `MakeDay` does).
        """
        tokens = cls._v8_legacy_tokens(source)
        if tokens is None:
            return None
        numbers = []  # type: List[int]
        month = None
        clock = None
        zone = None
        marker = None
        for kind, value in tokens:
            if kind == "num":
                if len(numbers) == 3:
                    return None
                numbers.append(value)
            elif kind == "clock":
                if clock is not None:
                    return None
                clock = value
            elif kind == "marker":
                marker = value
            elif kind == "zone":
                if numbers or clock is not None:
                    zone = value
                # Otherwise the word precedes the date: `new Date("GMT 5")`
                # names May 2001 without applying the timezone.
            else:
                lowered = value.lower()
                if len(lowered) >= 3 and lowered[:3] in cls._V8_MONTH_PREFIXES:
                    month = cls._V8_MONTH_PREFIXES.index(lowered[:3]) + 1
                elif numbers or clock is not None:
                    # An unknown word (`new Date("Mar 5 2026 xyz")`) is only
                    # ignored before any number or clock time.
                    return None
        if not numbers:
            return None
        slots = ["day", "year"] if month is not None else ["month", "day", "year"]
        fields = {}
        remaining = list(numbers)
        if remaining[0] == 0 or remaining[0] > 31:
            fields["year"] = remaining.pop(0)
            slots = [slot for slot in slots if slot != "year"]
        for value in remaining:
            if not slots:
                break
            fields[slots.pop(0)] = value
        year = fields.get("year", 2001)
        if year < 100:
            year += 2000 if year < 50 else 1900
        month = fields.get("month", month if month is not None else 1)
        day = fields.get("day", 1)
        if not 1 <= month <= 12 or not 1 <= day <= 31 or not 1 <= year <= 9999:
            return None
        hour = minute = second = micro = 0
        if clock is not None:
            hour, minute, second, micro = clock
        if marker is not None:
            if hour > 12:
                return None
            if marker == "pm":
                hour += 12 if hour < 12 else 0
            elif hour == 12:
                hour = 0
        if hour == 24 and (minute or second or micro):
            return None
        if zone is None:
            return cls._build_local(year, month, day, hour, minute, second, micro)
        return cls._build_zoned(year, month, day, hour, minute, second, micro, zone)

    @classmethod
    def format(cls, ms: float) -> str:
        """Format milliseconds matching Cosmokit Time.format."""
        abs_ms = abs(ms)
        if abs_ms >= cls.day - cls.hour / 2:
            return _js_number_to_string(_js_round(ms / cls.day)) + "d"
        elif abs_ms >= cls.hour - cls.minute / 2:
            return _js_number_to_string(_js_round(ms / cls.hour)) + "h"
        elif abs_ms >= cls.minute - cls.second / 2:
            return _js_number_to_string(_js_round(ms / cls.minute)) + "m"
        elif abs_ms >= cls.second:
            return _js_number_to_string(_js_round(ms / cls.second)) + "s"
        return _js_number_to_string(ms) + "ms"

    @classmethod
    def to_digits(cls, source: int, length: int = 2) -> str:
        """Format number padded with leading zeros matching Cosmokit Time.toDigits."""
        return _js_pad_start(_js_number_to_string(source), length)

    toDigits = to_digits

    @classmethod
    def template(cls, tmpl: str, time_val: Optional[datetime.datetime] = None) -> str:
        """Template format date matching Cosmokit Time.template."""
        if time_val is None:
            time_val = datetime.datetime.now()
        res = tmpl.replace("yyyy", str(time_val.year), 1)
        res = res.replace("yy", str(time_val.year)[2:], 1)
        res = res.replace("MM", cls.to_digits(time_val.month), 1)
        res = res.replace("dd", cls.to_digits(time_val.day), 1)
        res = res.replace("hh", cls.to_digits(time_val.hour), 1)
        res = res.replace("mm", cls.to_digits(time_val.minute), 1)
        res = res.replace("ss", cls.to_digits(time_val.second), 1)
        res = res.replace("SSS", cls.to_digits(int(time_val.microsecond / 1000), 3), 1)
        return res


class TracedProxy:
    """
    Traceable proxy wrapper binding a service or callable to a caller Context
    matching TS getTraceable(ctx, value).
    """
    def __init__(self, ctx: Any, target: Any, tracker: Optional[Dict[str, Any]] = None):
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_tracker", tracker or getattr(target, Symbols.tracker, None) or getattr(target, "_cordis_tracker", {}))

    @property
    def __class__(self) -> Any:
        try:
            return object.__getattribute__(self, "_target").__class__
        except Exception:
            return TracedProxy

    def __getattr__(self, name: str) -> Any:
        if name in (Symbols.original, "cordis.original"):
            return object.__getattribute__(self, "_target")
        if name in (Symbols.shadow, "cordis.shadow"):
            ctx = object.__getattribute__(self, "_ctx")
            return getattr(ctx, Symbols.shadow, getattr(ctx, "_parent", None))
        if name == "ctx":
            return object.__getattribute__(self, "_ctx")
        if name in ("_target", "_ctx", "_tracker"):
            return object.__getattribute__(self, name)
        target = object.__getattribute__(self, "_target")
        attr = getattr(target, name)
        if callable(attr):
            @functools.wraps(attr)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if "caller_ctx" not in kwargs:
                    try:
                        sig = inspect.signature(attr)
                        if "caller_ctx" in sig.parameters:
                            kwargs["caller_ctx"] = object.__getattribute__(self, "_ctx")
                    except (ValueError, TypeError):
                        pass
                res = attr(*args, **kwargs)
                return get_traceable(object.__getattribute__(self, "_ctx"), res)
            return wrapper
        return get_traceable(object.__getattribute__(self, "_ctx"), attr)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_ctx", "_target", "_tracker"):
            object.__setattr__(self, name, value)
        elif name in (Symbols.original, "cordis.original", "ctx"):
            return
        else:
            target = object.__getattribute__(self, "_target")
            setattr(target, name, value)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        target = object.__getattribute__(self, "_target")
        if callable(target):
            if "caller_ctx" not in kwargs:
                try:
                    sig = inspect.signature(target)
                    if "caller_ctx" in sig.parameters:
                        kwargs["caller_ctx"] = object.__getattribute__(self, "_ctx")
                except (ValueError, TypeError):
                    pass
            res = target(*args, **kwargs)
            return get_traceable(object.__getattribute__(self, "_ctx"), res)
        raise TypeError(f"Target '{target}' is not callable")

    def __getitem__(self, key: Any) -> Any:
        return object.__getattribute__(self, "_target")[key]

    def __setitem__(self, key: Any, value: Any) -> None:
        object.__getattribute__(self, "_target")[key] = value

    def __delitem__(self, key: Any) -> None:
        del object.__getattribute__(self, "_target")[key]

    def __len__(self) -> int:
        return len(object.__getattribute__(self, "_target"))

    def __contains__(self, item: Any) -> bool:
        return item in object.__getattribute__(self, "_target")

    def __iter__(self) -> Iterator[Any]:
        return iter(object.__getattribute__(self, "_target"))

    def __next__(self) -> Any:
        return next(object.__getattribute__(self, "_target"))

    def __enter__(self) -> Any:
        target = object.__getattribute__(self, "_target")
        if hasattr(target, "__enter__"):
            return target.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        target = object.__getattribute__(self, "_target")
        if hasattr(target, "__exit__"):
            return target.__exit__(exc_type, exc_val, exc_tb)
        return False

    async def __aenter__(self) -> Any:
        target = object.__getattribute__(self, "_target")
        if hasattr(target, "__aenter__"):
            return await target.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        target = object.__getattribute__(self, "_target")
        if hasattr(target, "__aexit__"):
            return await target.__aexit__(exc_type, exc_val, exc_tb)
        return False

    def __bool__(self) -> bool:
        return bool(object.__getattribute__(self, "_target"))

    def __str__(self) -> str:
        return str(object.__getattribute__(self, "_target"))

    def __eq__(self, other: Any) -> bool:
        target = object.__getattribute__(self, "_target")
        if isinstance(other, TracedProxy):
            return target == object.__getattribute__(other, "_target")
        return target == other

    def __hash__(self) -> int:
        return hash(object.__getattribute__(self, "_target"))

    def __repr__(self) -> str:
        return f"<TracedProxy target={object.__getattribute__(self, '_target')!r}>"


def get_traceable(ctx: Any, value: Any) -> Any:
    """
    Attach context tracing wrapper to a Service matching TS getTraceable.
    """
    if value is None or isinstance(value, (int, float, str, bool, dict, list, tuple, set, bytes, bytearray)):
        return value
    if isinstance(value, TracedProxy):
        return value
    # Never wrap Context or Fiber instances matching TS: if (value instanceof Context) return value
    if hasattr(value, "registry") and hasattr(value, "reflect") and hasattr(value, "extend"):
        return value
    if hasattr(value, "state") and hasattr(value, "assert_active") and hasattr(value, "_disposables"):
        return value
    # If value has shadow origin, unwrap matching TS: if (Object.hasOwn(value, symbols.shadow)) return proto
    shadow_val = getattr(value, "_shadow", None)
    if shadow_val is not None:
        return shadow_val

    # Determine tracker and noShadow behavior matching TS createTraceable
    tracker = getattr(value, Symbols.tracker, None) or getattr(value, "_cordis_tracker", None)
    no_shadow = False
    if isinstance(tracker, dict):
        no_shadow = tracker.get("noShadow", False) or tracker.get("no_shadow", False)

    effective_ctx = ctx
    is_shadow = getattr(ctx, "is_shadow", False) or getattr(ctx, "_shadow", None) is not None or getattr(ctx, "_shadow_fiber", None) is not None
    if is_shadow and not no_shadow:
        effective_ctx = getattr(ctx, "_shadow", getattr(ctx, "_parent", ctx)) or ctx

    from dsh.cordis.service import Service
    if isinstance(value, Service):
        return value._extend({"ctx": effective_ctx})
    if hasattr(value, "_extend") and not hasattr(value, "_mock_return_value") and callable(getattr(value, "_extend")):
        return value._extend({"ctx": effective_ctx})
    if tracker and not hasattr(value, "_mock_return_value"):
        return TracedProxy(effective_ctx, value, tracker=tracker if isinstance(tracker, dict) else {})
    if callable(value) and not inspect.isclass(value) and not hasattr(value, "_mock_return_value"):
        try:
            sig = inspect.signature(value)
            if "caller_ctx" in sig.parameters:
                return TracedProxy(effective_ctx, value)
        except Exception:
            pass
    return value


class _WithPropsProxy:
    def __init__(self, target: Any, props: Any):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_props", props)

    def __getattr__(self, name: str) -> Any:
        props = object.__getattribute__(self, "_props")
        target = object.__getattribute__(self, "_target")
        has_prop = False
        attr = None
        if isinstance(props, dict):
            if name in props and name != "constructor":
                attr = props[name]
                has_prop = True
        elif hasattr(props, name) and name != "constructor":
            attr = getattr(props, name)
            has_prop = True

        if not has_prop:
            attr = getattr(target, name)

        if callable(attr) and not inspect.isclass(attr):
            try:
                sig = inspect.signature(attr)
                if "caller_ctx" in sig.parameters:
                    return TracedProxy(target, attr)
            except Exception:
                pass
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        props = object.__getattribute__(self, "_props")
        target = object.__getattribute__(self, "_target")
        if isinstance(props, dict):
            if name in props and name != "constructor":
                props[name] = value
                return
        elif hasattr(props, name) and name != "constructor":
            setattr(props, name, value)
            return
        setattr(target, name, value)

    def __repr__(self) -> str:
        return f"<WithPropsProxy target={object.__getattribute__(self, '_target')!r} props={object.__getattribute__(self, '_props')!r}>"


def with_props(target: Any, props: Optional[Any] = None) -> Any:
    """
    Overlay properties onto a target matching TS withProps.
    """
    if not props:
        return target
    return _WithPropsProxy(target, props)


def build_outer_stack(offset: int = 0) -> Callable[[], List[str]]:
    """
    Capture a lazy stack-frame supplier matching TS buildOuterStack(offset = 0).
    """
    stack_lines = traceback.format_stack()
    filtered = stack_lines[:-1]
    if offset > 0 and len(filtered) >= offset:
        filtered = filtered[:-offset]

    def get_stack() -> List[str]:
        return list(filtered)

    return get_stack


def compose_error(action: Callable[..., Any], get_outer_stack: Optional[Callable[[], List[str]]] = None) -> Any:
    """
    Run a callback and splice outer call-site frames matching TS composeError.
    """
    if get_outer_stack is None:
        get_outer_stack = build_outer_stack()
    info = {"offset": 1, "error": Exception()}

    takes_info = False
    try:
        sig = inspect.signature(action)
        takes_info = len(sig.parameters) > 0
    except Exception:
        pass

    try:
        if takes_info:
            return action(info)
        return action()
    except Exception as e:
        if get_outer_stack and callable(get_outer_stack):
            outer = get_outer_stack()
            if outer:
                e._outer_stack = outer
        raise


def get_isolate_symbol(ctx: Any, name: str) -> Any:
    """
    Look up isolation symbol for a service name traversing the context prototype/parent chain matching TS ctx[symbols.isolate][name].
    """
    curr = ctx
    while curr is not None:
        iso_map = getattr(curr, "_isolated_keys", None)
        if iso_map is not None and name in iso_map:
            return iso_map[name]
        curr = getattr(curr, "_parent", None)
    if hasattr(ctx, "root") and hasattr(ctx.root, "_isolated_keys"):
        return ctx.root._isolated_keys.get(name)
    return None


def is_(type_str: str, value: Any = Ellipsis) -> Any:
    """Type predicate factory matching Cosmokit is().

    The reference is `type in globalThis && value instanceof globalThis[type]
    || Object.prototype.toString.call(value).slice(8, -1) === type`: the name
    is resolved to a global constructor or compared with the value's internal
    tag.  The Python mapping resolves the constructor names that exist here
    (`Object` every non-primitive, `Null` the Python `None`, `Undefined` the
    port's own ``undefined``, `ArrayBuffer`/`SharedArrayBuffer` the owning
    buffers `bytes`/`bytearray`, every ArrayBufferView name the `memoryview`,
    `WeakMap`/`WeakSet` the stdlib `weakref` containers), and a name the port
    does not map matches nothing, because a Python class name is not an
    internal tag (`is('Widget', new Widget())` is false in the reference: a
    module-scoped class is not in `globalThis`).

    LEGAL_ADAPTATION: `Symbol` has no Python equivalent; Python has one
    integer type, so an integer matches `Number` and `BigInt` alike; Python
    exposes one generic view type, so every typed-array name matches a
    `memoryview` regardless of its element type; and the port carries a
    JavaScript `Map` as a `dict`, which is also its plain-object
    representation, whose tag is `Object` rather than `Map` - a plain object
    is not a Map in the reference (`is('Map', {})` is false), so `Map`
    matches no Python value.  `is` is a Python keyword, so the exported
    predicate is spelled `is_` (the same spelling `Binary.is` keeps as an
    attribute).
    """

    def _check(val: Any) -> bool:
        if type_str == "Null":
            return val is None
        if type_str == "Undefined":
            # `Object.prototype.toString.call(undefined)` is '[object
            # Undefined]' while `Object.prototype.toString.call(null)` is
            # '[object Null]', so the two nullish tags are distinct
            # (`is('Undefined', null)` is false).  The port carries `null` as
            # ``None`` and `undefined` as its own ``_UNDEFINED`` sentinel, so
            # only the sentinel matches here and ``None`` answers `Null`.
            return val is _UNDEFINED
        if type_str == "Boolean":
            return isinstance(val, bool)
        if type_str == "Number":
            return isinstance(val, (int, float)) and not isinstance(val, bool)
        if type_str == "String":
            return isinstance(val, str)
        if type_str == "BigInt":
            return isinstance(val, int) and not isinstance(val, bool)
        if type_str == "Function":
            return isinstance(val, _JS_FUNCTION_TYPES)
        if type_str == "Array":
            return isinstance(val, (list, tuple))
        if type_str == "Date":
            return isinstance(val, datetime.datetime)
        if type_str == "RegExp":
            return isinstance(val, _REGEX_TYPE)
        if type_str in ("ArrayBuffer", "SharedArrayBuffer"):
            # `isArrayBufferLike`: only a buffer that owns its memory matches,
            # i.e. `bytes`/`bytearray`.  A view over one is not an ArrayBuffer
            # (`is('ArrayBuffer', new Uint8Array(2))` is false).
            return isinstance(val, (bytes, bytearray))
        if type_str in ("Uint8Array", "Uint8ClampedArray", "Int8Array", "Uint16Array",
                        "Int16Array", "Uint32Array", "Int32Array", "Float32Array",
                        "Float64Array", "BigInt64Array", "BigUint64Array", "DataView"):
            # `ArrayBuffer.isView`: a view matches, the buffer it views does
            # not (`is('Uint8Array', new ArrayBuffer(2))` is false).
            return isinstance(val, memoryview)
        if type_str == "Map":
            # A JavaScript `Map` is keyed by identity and is not a plain
            # object: its tag is '[object Map]' while a plain object's is
            # '[object Object]', so `is('Map', {})` is false in the reference
            # even though `is('Object', new Map())` is true.  The port carries
            # a JavaScript Map as a `dict`, which is also its plain-object
            # representation and therefore cannot be recognized as a Map (see
            # the LEGAL_ADAPTATION in the docstring).
            return False
        if type_str == "WeakMap":
            # `weakref.WeakKeyDictionary` is the stdlib container the port
            # uses where the reference keeps a `WeakMap` (an identity-keyed
            # collection, as in dsh/boot/app_boot.py, dsh/core/scope.py and
            # dsh/schedule/transaction.py); a plain object is not one.
            return isinstance(val, weakref.WeakKeyDictionary)
        if type_str == "Set":
            return isinstance(val, (set, frozenset))
        if type_str == "WeakSet":
            # A Python `set` is the JavaScript `Set`, not a `WeakSet`
            # (`is('WeakSet', new Set())` is false in the reference), and
            # `weakref.WeakSet` is the stdlib container the reference's
            # `WeakSet` corresponds to.
            return isinstance(val, weakref.WeakSet)
        if type_str == "Promise":
            import asyncio
            return isinstance(val, asyncio.Future)
        if type_str == "Error":
            return isinstance(val, Exception)
        if type_str in ("EvalError", "RangeError", "ReferenceError", "SyntaxError",
                        "TypeError", "URIError", "AggregateError"):
            return isinstance(val, Exception) and type(val).__name__ == type_str
        if type_str == "Proxy":
            # `Proxy` is in the typed domain of `GlobalConstructorNames`, but
            # `Proxy.prototype` is undefined, so V8's `value instanceof Proxy`
            # throws `TypeError: Function has non-object prototype 'undefined'
            # in instanceof check` for every object operand and answers false
            # for every primitive one (`InstanceofOperator` returns false for
            # a non-object left operand before it reads the prototype).
            if not _js_is_primitive(val):
                raise TypeError(
                    "Function has non-object prototype 'undefined' in instanceof check")
            return False
        if type_str == "Object":
            # `value instanceof Object` holds for every non-primitive value
            # (arrays, dates, regexps, maps, functions included); only the
            # ECMAScript primitives (and null/undefined) are rejected, so the
            # port's own undefined sentinel is rejected as well.
            return not _js_is_nullish(val) and not isinstance(val, (bool, int, float, str))
        # A name that is neither a global constructor nor the value's internal
        # tag never matches: `is('Widget', new Widget())` is false in the
        # reference, where a module-scoped class is not in `globalThis`.
        return False

    if value is Ellipsis:
        return _check
    return _check(value)


def _binary_from_source(source: Any) -> Any:
    """`Binary.fromSource`: an ArrayBuffer is returned as-is, a view is sliced."""
    if isinstance(source, memoryview):
        return source.tobytes()
    return source


#: Node's `Buffer.from(source, 'base64')` also accepts the base64url alphabet.
_BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
#: Node's base64 decoder also accepts the base64url substitutions ('-' -> 62, '_' -> 63).
_BASE64_LOOKUP = {char: index for index, char in enumerate(_BASE64_ALPHABET)}
_BASE64_LOOKUP["-"] = 62
_BASE64_LOOKUP["_"] = 63
_HEX_DIGITS = "0123456789abcdefABCDEF"


def _decode_base64(source: str) -> bytes:
    """Node-compatible base64 decode.

    `Buffer.from(source, 'base64')` never throws: characters outside the
    alphabet are skipped, a partial trailing group decodes its complete bytes
    and decoding stops at the first `=` padding character.
    """
    accumulator = 0
    bits = 0
    out = bytearray()
    for char in source:
        if char == "=":
            break
        value = _BASE64_LOOKUP.get(char)
        if value is None:
            continue
        accumulator = (accumulator << 6) | value
        bits += 6
        if bits >= 8:
            bits -= 8
            out.append((accumulator >> bits) & 0xFF)
    return bytes(out)


def _decode_hex(source: str) -> bytes:
    """Node-compatible hex decode.

    `Buffer.from(source, 'hex')` never throws: it stops at the first
    non-hexadecimal character and drops an odd trailing nibble.
    """
    nibbles: List[int] = []
    for char in source:
        if char not in _HEX_DIGITS:
            break
        nibbles.append(int(char, 16))
    if len(nibbles) % 2:
        nibbles.pop()
    out = bytearray()
    for index in range(0, len(nibbles), 2):
        out.append((nibbles[index] << 4) | nibbles[index + 1])
    return bytes(out)


class Binary:
    """Binary buffer and encoding helpers matching Cosmokit Binary."""

    #: Reference name `Binary.is` (`isArrayBufferLike`); `is` is a Python
    #: keyword, so the port keeps the module-wide `is_` spelling.
    @staticmethod
    def is_(source: Any) -> bool:
        """Return true for an ArrayBuffer-like value (a view is not one).

        `memoryview` maps to the reference's ArrayBufferView, `bytes` and
        `bytearray` to ArrayBuffer/SharedArrayBuffer.
        """
        return isinstance(source, (bytes, bytearray))

    @staticmethod
    def is_source(source: Any) -> bool:
        """`Binary.isSource`: an ArrayBuffer-like or an ArrayBuffer view."""
        return isinstance(source, (bytes, bytearray, memoryview))

    isSource = is_source

    @staticmethod
    def from_source(source: Any) -> Any:
        """`Binary.fromSource`: return the backing buffer of a view."""
        return _binary_from_source(source)

    fromSource = from_source

    @staticmethod
    def to_base64(source: Union[bytes, bytearray, memoryview]) -> str:
        source = _binary_from_source(source)
        return base64.b64encode(source).decode("ascii")

    toBase64 = to_base64

    @staticmethod
    def from_base64(source: str) -> bytes:
        return _decode_base64(source)

    fromBase64 = from_base64

    @staticmethod
    def to_hex(source: Union[bytes, bytearray, memoryview]) -> str:
        source = _binary_from_source(source)
        return binascii.hexlify(source).decode("ascii")

    toHex = to_hex

    @staticmethod
    def from_hex(source: str) -> bytes:
        return _decode_hex(source)

    fromHex = from_hex


# `Binary.is` cannot be spelled in the class body (`is` is a Python keyword),
# so the reference name is installed after the class is created.
setattr(Binary, "is", Binary.is_)

# Module-level aliases exported by cosmokit's types.ts.
base64_to_array_buffer = Binary.from_base64
base64ToArrayBuffer = Binary.from_base64
array_buffer_to_base64 = Binary.to_base64
arrayBufferToBase64 = Binary.to_base64
hex_to_array_buffer = Binary.from_hex
hexToArrayBuffer = Binary.from_hex
array_buffer_to_hex = Binary.to_hex
arrayBufferToHex = Binary.to_hex


def define_property(obj: Any, key: str, value: Any) -> Any:
    """Define an own property on obj matching Cosmokit defineProperty.

    The reference defines a writable, non-enumerable property and lets
    `Object.defineProperty` raise a TypeError for a target that cannot hold it;
    the port does not swallow that failure either.  A dict is the plain-object
    equivalent and receives a plain entry (Python has no enumerability, so the
    `enumerable: false` part of the descriptor cannot be represented).

    `Object.defineProperty` requires an object, so every ECMAScript primitive
    target (null, undefined, boolean, number, string) throws a TypeError with
    the reference's message, where a bare `setattr` reports an AttributeError.

    LEGAL_ADAPTATION: a target that is an object in the reference but a Python
    value with no attribute store (list, tuple, set, bytes, memoryview) cannot
    carry an own property, so `setattr` reports AttributeError there.
    """
    if obj is None or obj is _UNDEFINED or isinstance(obj, (bool, int, float, str)):
        raise TypeError("Object.defineProperty called on non-object")
    if isinstance(obj, dict):
        obj[key] = value
        return obj
    setattr(obj, key, value)
    return obj

defineProperty = define_property


def _js_apply_with_key(callback: Callable[..., Any], value: Any, key: str) -> Any:
    """LEGAL_ADAPTATION: JavaScript ignores surplus arguments, Python cannot.

    The reference always calls `callback(value, key)`; the callback arity picks
    the equivalent Python call -- fewer positional slots receive the leading
    arguments only (a ``() => ...`` transform that ignores both gets none) and
    surplus declared slots receive the port's ``undefined`` sentinel, see
    _js_supplied_arg_count and _js_call_args; a callback CPython cannot report
    is served by _js_call_callback from the reference's own argument list.
    A non-TypeError raised by the callback propagates unchanged.
    """
    # _js_call_callback replays the reference list for an unreported signature.
    return _js_call_callback(callback, (value, key))


def map_values(source: Dict[str, Any], callback: Callable[..., Any]) -> Dict[str, Any]:
    """Transform values of a dict matching Cosmokit mapValues.

    `Object.entries(source)` enumerates in ECMAScript own-key order, which
    `Object.fromEntries` then preserves.
    """
    res = {}
    for key in _js_own_enumerable_keys(source):
        res[key] = _js_apply_with_key(callback, _js_read_key(source, key), key)
    return res

mapValues = map_values
value_map = map_values
valueMap = map_values
