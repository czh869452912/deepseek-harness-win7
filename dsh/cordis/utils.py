"""
Cordis Utilities matching reference/vendor/cordis/src/utils.ts
Implements DisposableList, Symbol constants, Traceable proxy, and Stack builders.
"""

import functools
import inspect
import sys
import traceback
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, Tuple, TypeVar

T = TypeVar("T")


class DisposableList(Generic[T]):
    """
    Ordered collection of disposable values with O(1) deletion by value.
    Matching reference/vendor/cordis/src/utils.ts DisposableList.
    """

    def __init__(self) -> None:
        self._sn = 0
        self._map: Dict[int, T] = {}
        self._id_to_sn: Dict[int, int] = {}
        self._val_to_sn: Dict[Any, int] = {}

    @property
    def length(self) -> int:
        return len(self._map)

    def __len__(self) -> int:
        return len(self._map)

    def push(self, value: T) -> Callable[[], bool]:
        """
        Push a disposable item to the list.
        Returns a disposer function that removes this item.
        """
        self._sn += 1
        sn = self._sn
        self._map[sn] = value
        try:
            self._val_to_sn[value] = sn
        except TypeError:
            pass
        self._id_to_sn[id(value)] = sn

        def disposer() -> bool:
            return self.delete_by_sn(sn)

        return disposer

    def delete_by_sn(self, sn: int) -> bool:
        if sn in self._map:
            val = self._map.pop(sn)
            if id(val) in self._id_to_sn and self._id_to_sn[id(val)] == sn:
                del self._id_to_sn[id(val)]
            try:
                if val in self._val_to_sn and self._val_to_sn[val] == sn:
                    del self._val_to_sn[val]
            except TypeError:
                pass
            return True
        return False

    def delete(self, value: T) -> bool:
        """Delete an item by value or identity."""
        try:
            if value in self._val_to_sn:
                sn = self._val_to_sn[value]
                return self.delete_by_sn(sn)
        except TypeError:
            pass

        val_id = id(value)
        if val_id in self._id_to_sn:
            sn = self._id_to_sn[val_id]
            return self.delete_by_sn(sn)

        for sn, v in list(self._map.items()):
            if v == value or v is value:
                return self.delete_by_sn(sn)
        return False

    def clear(self) -> List[T]:
        """Clear all entries and return values in reverse registration order."""
        values = list(self._map.values())
        self._map.clear()
        self._id_to_sn.clear()
        self._val_to_sn.clear()
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
    """Return true for non-null objects and functions."""
    return value is not None and (hasattr(value, "__dict__") or isinstance(value, (dict, list, tuple, set)) or callable(value))


def is_nullable(value: Any) -> bool:
    """Return true for None or undefined-like values."""
    return value is None


isNullable = is_nullable


def capitalize(source: str) -> str:
    """Uppercase the first character of a string."""
    if not source:
        return ""
    return source[0].upper() + source[1:]


def uncapitalize(source: str) -> str:
    """Lowercase the first character of a string."""
    if not source:
        return ""
    return source[0].lower() + source[1:]


def camel_case(source: str) -> str:
    """Convert dash or underscore delimited text to camelCase."""
    import re
    if not source:
        return ""
    return re.sub(r"[_-]([a-zA-Z0-9])", lambda m: m.group(1).upper(), source)


camelCase = camel_case
camelize = camel_case


def hyphenate(source: str) -> str:
    """Convert text to dash-delimited parameter case matching Cosmokit hyphenate/paramCase."""
    import re
    if not source:
        return ""
    # Convert camelCase to hyphen-case
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", source)
    s2 = re.sub(r"[_\s]+", "-", s1)
    return s2.lower().strip("-")


paramCase = hyphenate
param_case = hyphenate


def snake_case(source: str) -> str:
    """Convert text to underscore-delimited snake_case."""
    import re
    if not source:
        return ""
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", source)
    s2 = re.sub(r"[-\s]+", "_", s1)
    return s2.lower().strip("_")


snakeCase = snake_case


class Time:
    """Time constants and parsing helpers matching Cosmokit Time."""
    millisecond = 1
    second = 1000
    minute = second * 60
    hour = minute * 60
    day = hour * 24
    week = day * 7

    @staticmethod
    def parse_time(source: str) -> float:
        """Parse time strings like '10s', '5m', '2h', '1d' into milliseconds."""
        import re
        if not source or not isinstance(source, str):
            return 0.0
        pattern = r"^(?:(\d+(?:\.\d+)?)\s*w)?\s*(?:(\d+(?:\.\d+)?)\s*d)?\s*(?:(\d+(?:\.\d+)?)\s*h)?\s*(?:(\d+(?:\.\d+)?)\s*m)?\s*(?:(\d+(?:\.\d+)?)\s*s)?$"
        match = re.match(pattern, source.strip())
        if not match:
            return 0.0
        w, d, h, m, s = match.groups()
        total = 0.0
        if w: total += float(w) * Time.week
        if d: total += float(d) * Time.day
        if h: total += float(h) * Time.hour
        if m: total += float(m) * Time.minute
        if s: total += float(s) * Time.second
        return total

    parseTime = parse_time

    @staticmethod
    def format(ms: float) -> str:
        """Format milliseconds into human-readable shorthand (e.g. '10s', '5m', '2h')."""
        abs_ms = abs(ms)
        if abs_ms >= Time.day - Time.hour / 2:
            return f"{round(ms / Time.day)}d"
        elif abs_ms >= Time.hour - Time.minute / 2:
            return f"{round(ms / Time.hour)}h"
        elif abs_ms >= Time.minute - Time.second / 2:
            return f"{round(ms / Time.minute)}m"
        elif abs_ms >= Time.second:
            return f"{round(ms / Time.second)}s"
        return f"{int(ms)}ms"


class TracedProxy:
    """
    Traceable proxy wrapper binding a service or callable to a caller Context
    matching TS getTraceable(ctx, value).
    """
    def __init__(self, ctx: Any, target: Any):
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_target", target)

    @property
    def __class__(self) -> Any:
        try:
            return object.__getattribute__(self, "_target").__class__
        except Exception:
            return TracedProxy

    def __getattr__(self, name: str) -> Any:
        if name == "ctx":
            return object.__getattribute__(self, "_ctx")
        if name in ("_target", "_ctx"):
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
                return attr(*args, **kwargs)
            return wrapper
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_ctx", "_target"):
            object.__setattr__(self, name, value)
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
            return target(*args, **kwargs)
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
    from dsh.cordis.service import Service
    if isinstance(value, Service):
        return value._extend({"ctx": ctx})
    if hasattr(value, "_extend") and not hasattr(value, "_mock_return_value") and callable(getattr(value, "_extend")):
        return value._extend({"ctx": ctx})
    if hasattr(value, "_cordis_tracker") and not hasattr(value, "_mock_return_value"):
        return TracedProxy(ctx, value)
    if hasattr(value, Symbols.tracker) and not hasattr(value, "_mock_return_value"):
        return TracedProxy(ctx, value)
    if callable(value) and not inspect.isclass(value) and not hasattr(value, "_mock_return_value"):
        return TracedProxy(ctx, value)
    return value


def with_props(receiver: Any, service: Any) -> Any:
    """
    Combine receiver and service context properties matching TS withProps.
    """
    if receiver is None:
        return service
    return TracedProxy(receiver, service)


def build_outer_stack() -> Callable[[], List[str]]:
    """
    Capture the caller stack for effect diagnostics matching TS buildOuterStack().
    """
    stack_lines = traceback.format_stack()[:-1]
    filtered = []
    for line in stack_lines:
        line_str = line.strip()
        if line_str:
            filtered.append(f"    {line_str}")

    def get_stack() -> List[str]:
        return list(filtered)

    return get_stack


def compose_error(action: Callable[..., Any], get_outer_stack: Optional[Callable[[], List[str]]] = None) -> Any:
    """
    Execute an action and enrich errors with outer diagnostic stack.
    """
    try:
        return action()
    except Exception as e:
        if get_outer_stack and callable(get_outer_stack):
            outer = get_outer_stack()
            if outer:
                stack_msg = "\n".join(outer)
                if not hasattr(e, "_outer_stack"):
                    e._outer_stack = outer
        raise e
