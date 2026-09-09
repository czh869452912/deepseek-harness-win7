from typing import Any, Callable, Dict, List, Optional, Union


class Plugin:
    """
    Base class for Cordis plugins.
    A plugin provides a service or registers extensions (tools, event handlers, etc.) onto Context.
    """

    id: str = ""
    name: str = ""
    inject: List[str] = []
    provide: Optional[Union[str, List[str]]] = None
    intercept: Optional[Dict[str, bool]] = None
    Config: Any = None

    def __init__(self, ctx: Optional[Any] = None, config: Optional[Dict[str, Any]] = None):
        if ctx is not None and not hasattr(ctx, "fiber") and not hasattr(ctx, "inject") and isinstance(ctx, dict) and config is None:
            config = ctx
            ctx = None
        self.ctx: Optional[Any] = ctx
        self.config: Dict[str, Any] = config or {}

    def apply(self, ctx: Any, config: Optional[Any] = None) -> Any:
        """
        Plugin mounting logic matching TS Cordis apply(ctx, config).
        Overridden by subclass. May return a disposer callable or generator.
        """
        pass

    def teardown(self) -> None:
        """
        Plugin cleanup logic when unmounted (portable release extension).
        """
        pass


# PluginType union covering all 3 TS Cordis shapes:
# 1. Class/Constructor (subclass of Plugin or callable constructing plugin)
# 2. Function plugin (callable accepting ctx or ctx, config)
# 3. Object plugin (dict or instance with an apply method)
PluginType = Union[Plugin, Callable[..., Any], Dict[str, Any], Any]
