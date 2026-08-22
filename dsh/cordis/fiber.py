"""
Cordis Fiber lifecycle, effects, and config validation helpers
matching reference/vendor/cordis/src/fiber.ts
"""

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


class EffectMeta:
    """Tree node used to expose nested effect labels for diagnostics."""
    def __init__(self, label: str, children: Optional[List["EffectMeta"]] = None):
        self.label = label
        self.children: List["EffectMeta"] = children or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "children": [c.to_dict() for c in self.children]
        }


INACTIVE_EPOCH = "__INACTIVE__"


class Fiber:
    """
    Runtime instance of one plugin application matching reference/vendor/cordis/src/fiber.ts.
    Tracks dependency state, validated config, lifecycle effects, and cleanup.
    """

    _uid_counter = 0

    def __init__(self, parent_ctx: Any, plugin: Any, config: Any = None, runtime: Any = None):
        self.parent = parent_ctx
        self.plugin = plugin
        self.runtime = runtime
        self._config = config
        self.config = config
        self.store: Optional[Dict[str, Any]] = {}
        self.inertia: Optional[asyncio.Future] = None
        self.epoch: str = INACTIVE_EPOCH
        self._error: Optional[Exception] = None

        self._disposables: List[Callable[[], Any]] = []
        self._effect_metas: Dict[Callable[[], Any], EffectMeta] = {}

        if runtime is not None:
            # Plugin Fiber
            if hasattr(parent_ctx, "registry"):
                self.uid = parent_ctx.registry.counter
            else:
                Fiber._uid_counter += 1
                self.uid = Fiber._uid_counter
            self.ctx = parent_ctx.extend({"fiber": self}) if parent_ctx else None
            self.state = FiberState.PENDING
        else:
            # Root Fiber (runtime is None)
            self.uid = 0
            self.ctx = parent_ctx
            self.state = FiberState.ACTIVE

    @property
    def name(self) -> str:
        if self.plugin:
            if hasattr(self.plugin, "name") and self.plugin.name:
                return self.plugin.name
            if hasattr(self.plugin, "id") and self.plugin.id:
                return self.plugin.id
            if isinstance(self.plugin, type):
                return self.plugin.__name__
            return self.plugin.__class__.__name__
        return "root"

    def assert_active(self) -> None:
        if self.uid is None or self.state in (FiberState.DISPOSED, FiberState.UNLOADING):
            raise CordisError("INACTIVE_EFFECT", "cannot create effect on inactive context")

    def effect(self, execute_or_disposer: Any, label: str = "anonymous") -> Callable[[], Any]:
        """
        Register a cleanup-aware effect on this fiber.
        Supports functions, generators, and async generators.
        """
        self.assert_active()
        if self.state == FiberState.UNLOADING:
            raise CordisError("INACTIVE_EFFECT", "cannot create effect on inactive context")

        disposables: List[Callable[[], Any]] = []
        meta = EffectMeta(label=label)

        def collect_disposer(disp: Any) -> None:
            if callable(disp):
                disposables.append(disp)
                if disp not in self._disposables:
                    self._disposables.append(disp)

        if callable(execute_or_disposer):
            fn_name = getattr(execute_or_disposer, "__name__", "")
            if fn_name in ("disposer", "teardown", "cancel_effect", "cleanup") or "disposer" in label or "on(" in label:
                # Direct disposer function returned by registration API
                collect_disposer(execute_or_disposer)
            else:
                try:
                    res = execute_or_disposer()
                    if callable(res):
                        collect_disposer(res)
                    elif res is None or isinstance(res, (bool, int, float, str)):
                        pass
                    elif inspect.isgenerator(res):
                        for item in res:
                            if callable(item):
                                collect_disposer(item)
                    elif inspect.isasyncgen(res):
                        async def _consume_async_gen():
                            async for item in res:
                                if callable(item):
                                    collect_disposer(item)
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(_consume_async_gen())
                        except RuntimeError:
                            pass
                    elif inspect.isawaitable(res):
                        async def _await_res():
                            collected = await res
                            if callable(collected):
                                collect_disposer(collected)
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(_await_res())
                        except RuntimeError:
                            pass
                except Exception as e:
                    print(f"[Cordis Fiber Error] Exception in effect execution '{label}': {e}", file=sys.stderr)
                    raise e

        disposed = False

        def cancel_effect() -> None:
            nonlocal disposed
            if disposed:
                return
            disposed = True
            while disposables:
                disp = disposables.pop()
                if disp in self._disposables:
                    self._disposables.remove(disp)
                try:
                    r = disp()
                    if inspect.isawaitable(r):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(r)
                        except RuntimeError:
                            pass
                except Exception as e:
                    print(f"[Cordis Fiber Error] Exception running disposer '{label}': {e}", file=sys.stderr)

        self._effect_metas[cancel_effect] = meta
        return cancel_effect

    def get_effects(self) -> List[Dict[str, Any]]:
        """Return metadata for currently registered effects."""
        return [meta.to_dict() for meta in self._effect_metas.values()]

    def set_state(self, new_state: int) -> None:
        old_state = self.state
        if old_state == new_state:
            return
        self.state = new_state
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("internal/status", self, old_state)

    def set_epoch(self, epoch: str) -> None:
        """Update fiber epoch and trigger reload or unload transition if needed."""
        old_epoch = self.epoch
        if epoch == old_epoch:
            return
        self.epoch = epoch
        if epoch != INACTIVE_EPOCH and old_epoch == INACTIVE_EPOCH:
            self.set_state(FiberState.LOADING)
            self._reload()
        elif epoch == INACTIVE_EPOCH and old_epoch != INACTIVE_EPOCH:
            self.set_state(FiberState.UNLOADING)
            self._unload()

    def _reload(self) -> None:
        try:
            self.config = resolve_config(self.plugin, self._config)
            if hasattr(self.plugin, "apply") and callable(self.plugin.apply):
                self.plugin.apply(self.ctx)
            elif callable(self.plugin):
                self.plugin(self.ctx, self.config)
            self._error = None
            self.set_state(FiberState.ACTIVE)
        except Exception as e:
            self._error = e
            self.epoch = INACTIVE_EPOCH
            self.set_state(FiberState.FAILED)

    def _unload(self) -> None:
        while self._disposables:
            disposer = self._disposables.pop()
            try:
                res = disposer()
                if inspect.isawaitable(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        pass
            except Exception as e:
                print(f"[Cordis Fiber Error] Exception during unload for '{self.name}': {e}", file=sys.stderr)

        self.store = {}
        if self.epoch == INACTIVE_EPOCH:
            self.set_state(FiberState.PENDING if self.uid else FiberState.DISPOSED)

    async def dispose(self) -> None:
        """Dispose this fiber and execute disposers in strict reverse order."""
        if self.state in (FiberState.UNLOADING, FiberState.DISPOSED):
            return
        self.set_state(FiberState.UNLOADING)
        self.epoch = INACTIVE_EPOCH

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
        if self.ctx and hasattr(self.ctx, "emit"):
            self.ctx.emit("internal/plugin", self)

    def update(self, config: Any, no_save: bool = False) -> Any:
        """
        Validate and apply new config, then restart the plugin via internal/update waterfall.
        """
        self.assert_active()
        self._config = config
        if hasattr(self.ctx, "waterfall_sync"):
            return self.ctx.waterfall_sync("internal/update", config, no_save, lambda cfg=config: self.restart(cfg))
        return self.restart(config)

    def restart(self, new_config: Optional[Any] = None) -> None:
        """Dispose and immediately reload this plugin with current or new config."""
        self.assert_active()
        if new_config is not None:
            self._config = new_config
        self.set_epoch(INACTIVE_EPOCH)
        self.set_epoch("active_epoch")

    def __repr__(self) -> str:
        return f"<Fiber {self.name} state={self.state}>"
