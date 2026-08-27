"""Small lifecycle and context tracing utilities ported from Cordis."""

import inspect
from types import MethodType
from typing import Any, Callable, Dict, Generic, Iterator, List, Optional, TypeVar


T = TypeVar("T")


class Tracker:
    def __init__(
        self,
        associate: Optional[str] = None,
        property_name: Optional[str] = None,
        no_shadow: bool = False,
    ) -> None:
        self.associate = associate
        self.property = property_name
        self.no_shadow = no_shadow


class TraceableProxy:
    """Overlay a caller context on a service without mutating the provider."""

    def __init__(self, target: Any, ctx: Any, tracker: Tracker) -> None:
        object.__setattr__(self, "_trace_target", target)
        object.__setattr__(self, "_trace_ctx", ctx)
        object.__setattr__(self, "_trace_tracker", tracker)

    @property
    def original(self) -> Any:
        return object.__getattribute__(self, "_trace_target")

    def __getattr__(self, name: str) -> Any:
        target = object.__getattribute__(self, "_trace_target")
        ctx = object.__getattribute__(self, "_trace_ctx")
        tracker = object.__getattribute__(self, "_trace_tracker")
        if name == tracker.property:
            return ctx

        value = getattr(target, name)
        if inspect.ismethod(value) and value.__self__ is target:
            value = MethodType(value.__func__, self)
        return get_traceable(ctx, value)

    def __setattr__(self, name: str, value: Any) -> None:
        tracker = object.__getattribute__(self, "_trace_tracker")
        if name == tracker.property:
            raise AttributeError("trace context is read-only")
        setattr(object.__getattribute__(self, "_trace_target"), name, value)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        target = object.__getattribute__(self, "_trace_target")
        ctx = object.__getattribute__(self, "_trace_ctx")
        invoke_name = "symbols.invoke"
        invoke = getattr(target, invoke_name, None)
        if callable(invoke):
            if inspect.ismethod(invoke) and invoke.__self__ is target:
                invoke = MethodType(invoke.__func__, self)
            return get_traceable(ctx, invoke(*args, **kwargs))
        return get_traceable(ctx, target(*args, **kwargs))


def get_traceable(ctx: Any, value: T) -> T:
    if isinstance(value, TraceableProxy):
        return value
    tracker = getattr(value, "_cordis_tracker", None)
    if tracker is None:
        return value
    return TraceableProxy(value, ctx, tracker)  # type: ignore


class DisposableList(Generic[T]):
    """Ordered identity collection with stable removal and reverse clearing."""

    def __init__(self) -> None:
        self._serial = 0
        self._values: Dict[int, T] = {}
        self._identity: Dict[int, int] = {}

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[T]:
        return iter(self._values.values())

    def push(self, value: T) -> Callable[[], bool]:
        self._serial += 1
        serial = self._serial
        self._values[serial] = value
        self._identity[id(value)] = serial

        def remove() -> bool:
            current = self._values.get(serial)
            if current is not value:
                return False
            del self._values[serial]
            if self._identity.get(id(value)) == serial:
                del self._identity[id(value)]
            return True

        return remove

    def delete(self, value: T) -> bool:
        serial = self._identity.get(id(value))
        if serial is None or self._values.get(serial) is not value:
            return False
        del self._values[serial]
        del self._identity[id(value)]
        return True

    def clear(self) -> List[T]:
        values = list(self._values.values())
        self._values.clear()
        self._identity.clear()
        values.reverse()
        return values
