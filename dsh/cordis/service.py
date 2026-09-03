"""
Cordis Service base class matching reference/vendor/cordis/src/service.ts
"""

import sys
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

T = TypeVar("T")


class ServiceSymbols:
    """Symbol constants for Service lifecycle and metadata."""
    init = "symbols.init"
    check = "symbols.check"
    config = "symbols.config"
    invoke = "symbols.invoke"
    extend = "symbols.extend"
    tracker = "symbols.tracker"
    resolve_config = "symbols.resolveConfig"
    original = "cordis.original"
    shadow = "cordis.shadow"


class Service:
    """
    Base class for services that expose a named API on `ctx`.

    Subclasses call `super().__init__(ctx, name)` from their constructor.
    The service is registered immediately on context and automatically removed with the owning fiber.
    """

    init = ServiceSymbols.init
    check = ServiceSymbols.check
    config = ServiceSymbols.config
    invoke = ServiceSymbols.invoke
    extend = ServiceSymbols.extend
    tracker = ServiceSymbols.tracker
    resolve_config = ServiceSymbols.resolve_config
    original = ServiceSymbols.original
    shadow = ServiceSymbols.shadow

    provide_name: Optional[str] = None

    def __init__(self, ctx: Any, name: Optional[str] = None, allow_replace: bool = False):
        self.ctx = ctx
        resolved_name = name or getattr(self, "provide_name", None) or getattr(self, "name", None)
        if not resolved_name:
            cls_name = self.__class__.__name__.lower()
            if cls_name.endswith("service"):
                cls_name = cls_name[:-7]
            resolved_name = cls_name
        self.name = resolved_name

        check_fn = None
        if hasattr(self, ServiceSymbols.check) and callable(getattr(self, ServiceSymbols.check)):
            check_fn = getattr(self, ServiceSymbols.check)
        elif hasattr(self, "_check_availability") and callable(getattr(self, "_check_availability")):
            check_fn = getattr(self, "_check_availability")
        elif hasattr(self, "check") and callable(getattr(self, "check")):
            check_fn = getattr(self, "check")

        if hasattr(self.ctx, "provide"):
            self.ctx.provide(self.name, self, check=check_fn, allow_replace=allow_replace)
        elif hasattr(self.ctx, "set_service"):
            self.ctx.set_service(self.name, self, check=check_fn, allow_replace=allow_replace)

    def __getattr__(self, name: str) -> Any:
        if name in (ServiceSymbols.original, "cordis.original", "original", "symbols.original"):
            return getattr(self, "_original", self)
        if name in (ServiceSymbols.shadow, "cordis.shadow", "shadow", "symbols.shadow"):
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
        target_isolate = getattr(ctx, "_isolated_keys", {}) if ctx else {}
        self_isolate = getattr(self.ctx, "_isolated_keys", {}) if self.ctx else {}
        return target_isolate.get(self.name) == self_isolate.get(self.name)

    def _extend(self, props: Optional[Dict[str, Any]] = None) -> Any:
        """
        Derive extended service instance bound to child context matching TS Service[symbols.extend] (Object.create(this)).
        """
        target_ctx = props.get("ctx", self.ctx) if props else self.ctx
        if (target_ctx is self.ctx or target_ctx is None) and not props:
            return self
        import copy
        extended = copy.copy(self)
        if props:
            for k, v in props.items():
                setattr(extended, k, v)
        else:
            extended.ctx = target_ctx
        extended._original = getattr(self, "_original", self)
        return extended

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
