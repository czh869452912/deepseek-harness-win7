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

    provide_name: Optional[str] = None

    def __init__(self, ctx: Any, name: Optional[str] = None):
        self.ctx = ctx
        resolved_name = name or getattr(self, "provide_name", None) or getattr(self, "name", None) or self.__class__.__name__.lower()
        if resolved_name.endswith("service"):
            resolved_name = resolved_name[:-7]
        self.name = resolved_name

        check_fn = getattr(self, self.check, None)
        if not callable(check_fn) and hasattr(self, "_check_availability"):
            check_fn = getattr(self, "_check_availability")

        if hasattr(self.ctx, "set_service"):
            self.ctx.set_service(self.name, self, check=check_fn)
        elif hasattr(self.ctx, "provide"):
            self.ctx.provide(self.name, self, check=check_fn)

    def resolve_intercept_config(self, base: Optional[Any] = None, head: Optional[Any] = None) -> Any:
        """
        Merge intercept config from ancestors with optional base and head values.
        Entries added closer to root apply first.
        """
        configs: List[Dict[str, Any]] = []
        curr = self.ctx
        while curr is not None:
            intercept_map = getattr(curr, "_intercept_map", {})
            if self.name in intercept_map:
                configs.insert(0, intercept_map[self.name])
            curr = getattr(curr, "_parent", None)

        if base:
            configs.insert(0, base if isinstance(base, dict) else {"base": base})
        if head:
            configs.append(head if isinstance(head, dict) else {"head": head})

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

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """
        Support callable services matching Service.invoke.
        """
        invoke_fn = getattr(self, self.invoke, None)
        if callable(invoke_fn):
            return invoke_fn(*args, **kwargs)
        raise TypeError(f"Service '{self.name}' is not callable")

    def __repr__(self) -> str:
        return f"<Service {self.name}>"
