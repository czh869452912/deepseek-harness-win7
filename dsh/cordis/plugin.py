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

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config: Dict[str, Any] = config or {}
        self.ctx: Optional[Any] = None

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
