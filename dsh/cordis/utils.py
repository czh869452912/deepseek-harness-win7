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


class TracedProxy:
    """
    Traceable proxy wrapper binding a service or callable to a caller Context
    matching TS getTraceable(ctx, value).
    """
    def __init__(self, ctx: Any, target: Any):
        self._ctx = ctx
        self._target = target

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._target, name)
        if callable(attr):
            @functools.wraps(attr)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if "caller_ctx" not in kwargs:
                    sig = inspect.signature(attr)
                    if "caller_ctx" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                        kwargs["caller_ctx"] = self._ctx
                return attr(*args, **kwargs)
            return wrapper
        return get_traceable(self._ctx, attr)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if callable(self._target):
            if "caller_ctx" not in kwargs:
                sig = inspect.signature(self._target)
                if "caller_ctx" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    kwargs["caller_ctx"] = self._ctx
            return self._target(*args, **kwargs)
        raise TypeError(f"Target '{self._target}' is not callable")

    def __repr__(self) -> str:
        return f"<TracedProxy target={self._target!r}>"


def get_traceable(ctx: Any, value: Any) -> Any:
    """
    Attach context tracing wrapper to a value matching TS getTraceable.
    """
    if value is None or isinstance(value, (int, float, str, bool)):
        return value
    if isinstance(value, TracedProxy):
        return value
    if hasattr(value, "ctx") or callable(value):
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
