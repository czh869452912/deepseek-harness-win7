"""
Cordis Utilities matching reference/vendor/cordis/src/utils.ts
Implements DisposableList, Symbol constants, Traceable proxy, and Stack builders.
"""

import copy
import functools
import inspect
import sys
import traceback
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, Set, Tuple, TypeVar

T = TypeVar("T")


def clone(value: Any) -> Any:
    """Deep clone a value matching Cosmokit clone."""
    return copy.deepcopy(value)


import math
import re
import datetime
from collections import OrderedDict


def clone(value: Any) -> Any:
    """Deep clone a value matching Cosmokit clone."""
    return copy.deepcopy(value)


def deep_equal(a: Any, b: Any, strict: bool = False) -> bool:
    """Deep equality check matching Cosmokit deepEqual."""
    if a is b:
        return True
    if a == b:
        # Check bool vs int: in Python True == 1 is True, but TS 1 === true is False!
        if isinstance(a, bool) != isinstance(b, bool):
            return False
        return True
    if type(a) != type(b):
        # Allow numbers int vs float
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return not (isinstance(a, bool) or isinstance(b, bool)) and a == b
        # Allow dict vs OrderedDict
        if isinstance(a, dict) and isinstance(b, dict):
            pass
        else:
            return False
    if isinstance(a, dict):
        if len(a) != len(b):
            return False
        for k in a:
            if k not in b or not deep_equal(a[k], b[k], strict=strict):
                return False
        return True
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        for x, y in zip(a, b):
            if not deep_equal(x, y, strict=strict):
                return False
        return True
    if isinstance(a, type(re.compile(""))) and isinstance(b, type(re.compile(""))):
        return a.pattern == b.pattern and a.flags == b.flags
    if isinstance(a, (datetime.datetime, datetime.date)) and isinstance(b, (datetime.datetime, datetime.date)):
        return a == b
    return False


def pick(obj: Dict[str, Any], keys: Optional[Any] = None, forced: bool = False) -> Dict[str, Any]:
    """Pick specified keys from a dictionary matching Cosmokit pick."""
    if keys is None:
        return dict(obj)
    res = {}
    for k in keys:
        if forced or (k in obj and obj[k] is not None):
            res[k] = obj.get(k)
        elif k in obj:
            res[k] = obj[k]
    return res


def omit(obj: Dict[str, Any], keys: Optional[Any] = None) -> Dict[str, Any]:
    """Omit specified keys from a dictionary matching Cosmokit omit."""
    if keys is None:
        return dict(obj)
    key_set = set(keys)
    return {k: v for k, v in obj.items() if k not in key_set}


def value_map(obj: Dict[str, Any], transform: Callable[..., Any]) -> Dict[str, Any]:
    """Transform values of a dictionary matching Cosmokit valueMap."""
    res = {}
    for k, v in obj.items():
        sig = None
        try:
            sig = inspect.signature(transform)
        except Exception:
            pass
        if sig is not None:
            params = list(sig.parameters.values())
            takes_two = len(params) >= 2 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            if takes_two:
                res[k] = transform(v, k)
            else:
                res[k] = transform(v)
        else:
            try:
                res[k] = transform(v, k)
            except TypeError:
                res[k] = transform(v)
    return res


def filter_keys(obj: Dict[str, Any], predicate: Callable[..., bool]) -> Dict[str, Any]:
    """Filter dictionary keys matching Cosmokit filterKeys."""
    res = {}
    try:
        sig = inspect.signature(predicate)
        params = list(sig.parameters.values())
        has_two_params = len(params) >= 2 or any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    except Exception:
        has_two_params = False

    for k, v in obj.items():
        if has_two_params:
            if predicate(k, v):
                res[k] = v
        else:
            if predicate(k):
                res[k] = v
    return res


def capitalize(source: str) -> str:
    """Uppercase the first character of a string."""
    if not source:
        return source or ""
    return source[0].upper() + source[1:]


def uncapitalize(source: str) -> str:
    """Lowercase the first character of a string."""
    if not source:
        return source or ""
    return source[0].lower() + source[1:]


def camel_case(source: str) -> str:
    """Convert dash or underscore delimited text to camelCase matching Cosmokit camelCase."""
    if not source:
        return source or ""
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
    """Interpolate {key} or {{key}} placeholders in a string matching Cosmokit template."""
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


symbols = Symbols()


def is_object(value: Any) -> bool:
    """Return true for non-null objects and functions matching TS isObject."""
    if value is None:
        return False
    if isinstance(value, (int, float, str, bool, bytes, bytearray)):
        return False
    return True


def is_nullable(value: Any) -> bool:
    """Return true for None or undefined-like values."""
    return value is None


isNullable = is_nullable


def noop(*args: Any, **kwargs: Any) -> None:
    """No-op callback matching Cosmokit noop."""
    return None


def is_non_nullable(value: Any) -> bool:
    """Return true when value is not None."""
    return value is not None


def is_plain_object(data: Any) -> bool:
    """Return true for non-array dict values."""
    return bool(data and isinstance(data, dict))


def trim_slash(source: str) -> str:
    """Trim leading and trailing slashes."""
    return source.strip("/")


def sanitize(path: str) -> str:
    """Normalize path."""
    import posixpath
    return posixpath.normpath(path)


def contain(array1: Any, array2: Any) -> bool:
    """Return true when every item in array2 is present in array1."""
    return all(item in array1 for item in array2)


def intersection(array1: Any, array2: Any) -> List[Any]:
    """Return items that appear in both arrays."""
    return [item for item in array1 if item in array2]


def difference(array1: Any, array2: Any) -> List[Any]:
    """Return items from array1 that do not appear in array2."""
    return [item for item in array1 if item not in array2]


def union(array1: Any, array2: Any) -> List[Any]:
    """Return the set-union of two arrays while preserving first occurrence order."""
    res = []
    seen = set()
    for item in list(array1) + list(array2):
        try:
            if item not in seen:
                seen.add(item)
                res.append(item)
        except TypeError:
            if item not in res:
                res.append(item)
    return res


def deduplicate(array: Any) -> List[Any]:
    """Remove duplicate values while preserving first occurrence order."""
    res = []
    seen = set()
    for item in array:
        try:
            if item not in seen:
                seen.add(item)
                res.append(item)
        except TypeError:
            if item not in res:
                res.append(item)
    return res


def remove(lst: List[Any], item: Any) -> bool:
    """Remove one item from a list and report whether it was found."""
    try:
        lst.remove(item)
        return True
    except ValueError:
        return False


def make_array(source: Any) -> List[Any]:
    """Normalize nullish, scalar, or array input to a list."""
    if source is None:
        return []
    if isinstance(source, list):
        return source
    if isinstance(source, (tuple, set)):
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

    _timezone_offset = 0

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
        if date is None:
            date = datetime.datetime.now()
        elif isinstance(date, (int, float)):
            date = datetime.datetime.fromtimestamp(date / 1000.0)
        if offset is None:
            offset = cls._timezone_offset
        ts_ms = date.timestamp() * 1000.0
        return int(math.floor((ts_ms / cls.minute - offset) / 1440))

    getDateNumber = get_date_number

    @classmethod
    def from_date_number(cls, value: int, offset: Optional[int] = None) -> datetime.datetime:
        if offset is None:
            offset = cls._timezone_offset
        ts_ms = value * cls.day + offset * cls.minute
        return datetime.datetime.fromtimestamp(ts_ms / 1000.0)

    fromDateNumber = from_date_number

    _TIME_REGEX = re.compile(
        r"^(?:(\d+(?:\.\d+)?)w(?:eek(?:s)?)?)?"
        r"(?:(\d+(?:\.\d+)?)d(?:ay(?:s)?)?)?"
        r"(?:(\d+(?:\.\d+)?)h(?:our(?:s)?)?)?"
        r"(?:(\d+(?:\.\d+)?)m(?:in(?:ute)?(?:s)?)?)?"
        r"(?:(\d+(?:\.\d+)?)s(?:ec(?:ond)?(?:s)?)?)?$"
    )

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

    @classmethod
    def parse_date(cls, date_str: str) -> datetime.datetime:
        """Parse date matching Cosmokit Time.parseDate."""
        parsed = cls.parse_time(date_str)
        if parsed:
            return datetime.datetime.now() + datetime.timedelta(milliseconds=parsed)
        now = datetime.datetime.now()
        if re.match(r"^\d{1,2}(:\d{1,2}){1,2}$", date_str):
            parts = [int(p) for p in date_str.split(":")]
            h = parts[0]
            m = parts[1] if len(parts) > 1 else 0
            s = parts[2] if len(parts) > 2 else 0
            return now.replace(hour=h, minute=m, second=s, microsecond=0)
        return now

    parseDate = parse_date

    @classmethod
    def format(cls, ms: float) -> str:
        """Format milliseconds matching Cosmokit Time.format."""
        abs_ms = abs(ms)
        def _round_half_up(val: float) -> int:
            return int(math.floor(val + 0.5))

        if abs_ms >= cls.day - cls.hour / 2:
            return f"{_round_half_up(ms / cls.day)}d"
        elif abs_ms >= cls.hour - cls.minute / 2:
            return f"{_round_half_up(ms / cls.hour)}h"
        elif abs_ms >= cls.minute - cls.second / 2:
            return f"{_round_half_up(ms / cls.minute)}m"
        elif abs_ms >= cls.second:
            return f"{_round_half_up(ms / cls.second)}s"

        if isinstance(ms, float) and ms.is_integer():
            return f"{int(ms)}ms"
        return f"{ms}ms"

    @classmethod
    def to_digits(cls, source: int, length: int = 2) -> str:
        """Format number padded with leading zeros matching Cosmokit Time.toDigits."""
        return str(source).zfill(length)

    toDigits = to_digits

    @classmethod
    def template(cls, tmpl: str, time_val: Optional[datetime.datetime] = None) -> str:
        """Template format date matching Cosmokit Time.template."""
        if time_val is None:
            time_val = datetime.datetime.now()
        res = tmpl.replace("yyyy", str(time_val.year))
        res = res.replace("yy", str(time_val.year)[2:])
        res = res.replace("MM", cls.to_digits(time_val.month))
        res = res.replace("dd", cls.to_digits(time_val.day))
        res = res.replace("hh", cls.to_digits(time_val.hour))
        res = res.replace("mm", cls.to_digits(time_val.minute))
        res = res.replace("ss", cls.to_digits(time_val.second))
        res = res.replace("SSS", cls.to_digits(int(time_val.microsecond / 1000), 3))
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
