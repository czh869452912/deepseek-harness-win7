import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, List, Optional, Union


class FiberState:
    PENDING = 0
    LOADING = 1
    ACTIVE = 2
    FAILED = 3
    DISPOSED = 4
    UNLOADING = 5


class CordisError(Exception):
    """Framework error with a stable error code."""
    def __init__(self, code: str, message: Optional[str] = None):
        self.code = code
        super().__init__(message or code)


class ValidationError(TypeError):
    """Error raised when plugin configuration fails validation."""
    def __init__(self, issues: List[Any]):
        msg = "invalid config:\n" + "\n".join(f"  - {issue}" for issue in issues)
        super().__init__(msg)


def resolve_config(plugin: Any, config: Any) -> Any:
    """
    Validate and normalize config for a plugin runtime before it starts.
    """
    schema = getattr(plugin, "schema", None) or getattr(plugin, "Config", None)
    if not schema:
        return config
    if hasattr(schema, "validate") and callable(schema.validate):
        res = schema.validate(config)
        if isinstance(res, dict) and "issues" in res and res["issues"]:
            raise ValidationError(res["issues"])
        return res.get("value", config)
    return config


class Fiber:
    """
    Runtime instance of one plugin application.
    Tracks dependency state, validated config, lifecycle effects, and cleanup.
    """
    _uid_counter = 0

    def __init__(self, ctx: Any, plugin: Any, config: Any = None):
        Fiber._uid_counter += 1
        self.uid: Optional[int] = Fiber._uid_counter
        self.ctx = ctx
        self.plugin = plugin
        self._config = config
        self.config = config
        self.state = FiberState.PENDING
        self.store: Optional[Dict[str, Any]] = None
        self.inertia: Optional[Any] = None
        self._disposables: List[Callable[[], Any]] = []
        self._hooks: Dict[str, List[Callable[..., Any]]] = {}

    @property
    def name(self) -> str:
        if hasattr(self.plugin, "name") and self.plugin.name:
            return self.plugin.name
        if hasattr(self.plugin, "id") and self.plugin.id:
            return self.plugin.id
        if isinstance(self.plugin, type):
            return self.plugin.__name__
        return self.plugin.__class__.__name__

    def assert_active(self) -> None:
        if self.state in (FiberState.DISPOSED, FiberState.UNLOADING):
            raise CordisError("INACTIVE_EFFECT", "cannot create effect on inactive context")

    def effect(self, cleanup_func: Callable[[], Any], label: str = "") -> Callable[[], None]:
        """
        Store a reversible cleanup function as an effect on this fiber.
        Cleanup is executed when the fiber unloads or when the returned cancel function is called.
        """
        self.assert_active()
        if not callable(cleanup_func):
            return lambda: None

        self._disposables.append(cleanup_func)
        disposed = False

        def cancel_effect() -> None:
            nonlocal disposed
            if disposed:
                return
            disposed = True
            if cleanup_func in self._disposables:
                self._disposables.remove(cleanup_func)
            try:
                res = cleanup_func()
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as e:
                print(f"[Cordis Fiber Error] Exception running disposer '{label}': {e}", file=sys.stderr)

        return cancel_effect

    def set_state(self, new_state: int) -> None:
        old_state = self.state
        if old_state == new_state:
            return
        self.state = new_state
        if hasattr(self.ctx, "emit"):
            self.ctx.emit("internal/status", self, old_state)

    async def dispose(self) -> None:
        """
        Dispose this fiber: unload the plugin by executing disposers in reverse order.
        """
        if self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
            return
        self.set_state(FiberState.UNLOADING)

        # Run disposers in strict reverse registration order
        while self._disposables:
            disposer = self._disposables.pop()
            try:
                res = disposer()
                if inspect.isawaitable(res):
                    await res
            except Exception as e:
                print(f"[Cordis Fiber Error] Exception in disposer teardown for '{self.name}': {e}", file=sys.stderr)

        self.uid = None
        self.set_state(FiberState.DISPOSED)
        if hasattr(self.ctx, "emit"):
            self.ctx.emit("internal/plugin", self)

    def __repr__(self) -> str:
        return f"<Fiber {self.name} state={self.state}>"
