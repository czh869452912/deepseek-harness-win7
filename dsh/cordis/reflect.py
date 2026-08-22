from typing import Any, Callable, Dict, Optional


class ReflectService:
    """
    Reflection layer backing Context service resolution, proxy lookup, and intercept events.
    """
    def __init__(self, ctx: Any):
        self.ctx = ctx

    def get(self, ctx: Any, name: str, default: Any = None) -> Any:
        """
        Lookup service by name, notifying internal/get waterfall hook if present.
        """
        val = ctx.get_service(name, default)
        if hasattr(ctx, "waterfall_sync"):
            return ctx.waterfall_sync("internal/get", val, ctx, name)
        return val

    def on_set(self, ctx: Any, name: str, value: Any) -> None:
        """
        Notifies internal/service events after a service has been set on context.
        """
        if hasattr(ctx, "emit"):
            ctx.emit("internal/service", ctx, name, value)
