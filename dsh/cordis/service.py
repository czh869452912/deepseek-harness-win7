"""
Cordis Service base class matching reference/vendor/cordis/src/service.ts
"""

import sys
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from dsh.cordis.utils import symbols

T = TypeVar("T")


class ServiceSymbols:
    """Symbol constants for Service lifecycle and metadata."""
    init = symbols.init
    check = symbols.check
    config = symbols.config
    invoke = symbols.invoke
    extend = symbols.extend
    tracker = symbols.tracker
    resolve_config = symbols.resolve_config
    original = symbols.original
    shadow = symbols.shadow
    filter = symbols.filter


class _ServiceExtendedProxy:
    """
    Lightweight prototype proxy delegating to original service instance matching TS Object.create(this).
    """
    def __init__(self, target: Any, props: Optional[Dict[str, Any]] = None):
        self.__dict__["_target"] = target
        self.__dict__["_props"] = dict(props or {})
        self.__dict__["_original"] = getattr(target, "_original", target)
        self.__dict__["ctx"] = self.__dict__["_props"].get("ctx", getattr(target, "ctx", None))
        self.__dict__["name"] = getattr(target, "name", "")

    def __getattr__(self, name: str) -> Any:
        if name in self.__dict__:
            return self.__dict__[name]
        if "_props" in self.__dict__ and name in self.__dict__["_props"]:
            return self.__dict__["_props"][name]
        target = self.__dict__["_target"]
        attr = getattr(target, name)
        import inspect, types
        if inspect.ismethod(attr) and getattr(attr, "__self__", None) is target:
            return types.MethodType(attr.__func__, self)
        return attr

    def __setattr__(self, name: str, value: Any) -> None:
        if "_props" in self.__dict__ and name in self.__dict__["_props"]:
            self.__dict__["_props"][name] = value
        else:
            self.__dict__[name] = value

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.__dict__["_target"](*args, **kwargs)

    @property
    def __class__(self) -> Any:
        return self.__dict__["_target"].__class__

    def __repr__(self) -> str:
        return f"<Extended {repr(self.__dict__['_target'])}>"


class Service:
    """
    Base class for services that expose a named API on `ctx`.

    Subclasses call `super().__init__(ctx, name)` from their constructor.
    The service is registered immediately on context and automatically removed with the owning fiber.
    """

    init = symbols.init
    check = symbols.check
    config = symbols.config
    invoke = symbols.invoke
    extend = symbols.extend
    tracker = symbols.tracker
    resolve_config = symbols.resolve_config
    original = symbols.original
    shadow = symbols.shadow
    filter = symbols.filter

    provide: Optional[Any] = None
    provide_name: Optional[str] = None

    def __init__(self, ctx: Any, name: Optional[str] = None, allow_replace: bool = False, **kwargs: Any):
        self.ctx = ctx
        resolved_name = name or getattr(self, "provide", None) or getattr(self, "provide_name", None) or getattr(self, "name", None)
        if isinstance(resolved_name, (list, tuple)) and resolved_name:
            resolved_name = resolved_name[0]
        if not resolved_name:
            cls_name = self.__class__.__name__.lower()
            if cls_name.endswith("service"):
                cls_name = cls_name[:-7]
            resolved_name = cls_name
        self.name = resolved_name

        check_fn = None
        if hasattr(self, symbols.check) and callable(getattr(self, symbols.check)):
            check_fn = getattr(self, symbols.check)
        elif hasattr(self, "_check_availability") and callable(getattr(self, "_check_availability")):
            check_fn = getattr(self, "_check_availability")
        elif "check" in self.__class__.__dict__ and callable(getattr(self, "check")):
            check_fn = getattr(self, "check")

        if self.ctx is not None:
            if hasattr(self.ctx, "provide"):
                self.ctx.provide(self.name, self, check=check_fn, allow_replace=allow_replace)
            elif hasattr(self.ctx, "reflect") and hasattr(self.ctx.reflect, "provide"):
                self.ctx.reflect.provide(self.ctx, self.name, self, check=check_fn, allow_replace=allow_replace)
            else:
                raise RuntimeError(f"Context {self.ctx} does not support provide")

    def __getattr__(self, name: str) -> Any:
        if name in (symbols.original, "cordis.original", "original", "symbols.original"):
            return getattr(self, "_original", self)
        if name in (symbols.shadow, "cordis.shadow", "shadow", "symbols.shadow"):
            return getattr(self.ctx, "cordis.shadow", getattr(self.ctx, "_parent", None))
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def resolve_intercept_config(self, base: Optional[Any] = None, head: Optional[Any] = None) -> Any:
        """
        Merge intercept config from ancestors with optional base and head values.
        Entries added closer to root apply first.
        """
        configs: List[Any] = []
        curr = self.ctx
        while curr is not None:
            intercept_map = getattr(curr, "_intercept_map", {})
            if self.name in intercept_map:
                configs.insert(0, intercept_map[self.name])
            curr = getattr(curr, "_parent", None)

        if base is not None:
            configs.insert(0, base)
        if head is not None:
            configs.append(head)

        config_cls = getattr(self, "Config", None)
        if config_cls and hasattr(config_cls, "merge") and callable(getattr(config_cls, "merge")):
            return config_cls.merge(*configs)

        res: Dict[str, Any] = {}
        for cfg in configs:
            if isinstance(cfg, dict):
                res.update(cfg)
        return res

    def filter(self, ctx: Any) -> bool:
        """
        Service isolation filter matching TS Service[symbols.filter].
        Checks whether target context has the same isolation label for this service.
        """
        from dsh.cordis.utils import get_isolate_symbol
        return get_isolate_symbol(ctx, self.name) == get_isolate_symbol(self.ctx, self.name)

    def _extend(self, props: Optional[Dict[str, Any]] = None) -> Any:
        """
        Derive extended service instance bound to child context matching TS Service[symbols.extend] (Object.create(this)).
        """
        return _ServiceExtendedProxy(self, props)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """
        Support callable services matching Service.invoke.
        """
        invoke_fn = getattr(self, "invoke", None) or getattr(self, "_invoke", None)
        if not callable(invoke_fn) and hasattr(self, ServiceSymbols.invoke):
            candidate = getattr(self, ServiceSymbols.invoke)
            if callable(candidate):
                invoke_fn = candidate
        if callable(invoke_fn):
            return invoke_fn(*args, **kwargs)
        raise TypeError(f"Service '{self.name}' is not callable")

    def __repr__(self) -> str:
        return f"<Service {self.name}>"
