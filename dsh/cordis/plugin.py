import inspect
from typing import Any, Callable, Dict, List, Optional, Union


class Plugin:
    """
    Base class for Cordis plugins.
    A plugin provides a service or registers extensions (tools, event handlers, etc.) onto Context.
    """

    id: str = ""
    name: str = ""
    inject: List[str] = []

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config: Dict[str, Any] = config or {}
        self.ctx: Optional[Any] = None

    def apply(self, ctx: Any) -> None:
        """
        Plugin mounting logic. Overridden by subclass.
        """
        pass

    def teardown(self) -> None:
        """
        Plugin cleanup logic when unmounted.
        """
        pass


PluginType = Union[Plugin, Callable[[Any], None]]


def _accepts_config(callback: Callable[..., Any]) -> bool:
    """Whether a plugin callback accepts the upstream ``(ctx, config)`` pair."""
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return True
    positional = [
        parameter for parameter in signature.parameters.values()
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    return any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    ) or len(positional) >= 2


def invoke_plugin(plugin: Any, ctx: Any, config: Any) -> Any:
    """Invoke function, class, or object plugins with Cordis argument semantics."""
    if inspect.isclass(plugin):
        instance = plugin(ctx, config)
        init = getattr(instance, "init", None)
        return init() if callable(init) else None

    callback = getattr(plugin, "apply", None)
    if not callable(callback):
        callback = plugin
    if not callable(callback):
        raise TypeError("Invalid plugin")
    if _accepts_config(callback):
        return callback(ctx, config)
    return callback(ctx)
