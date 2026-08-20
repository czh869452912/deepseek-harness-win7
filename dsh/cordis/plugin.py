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
