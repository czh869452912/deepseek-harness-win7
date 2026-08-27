"""Cordis Fiber lifecycle and reversible effects."""

import asyncio
import inspect
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional

from dsh.cordis.plugin import invoke_plugin
from dsh.cordis.utils import DisposableList


class FiberState:
    PENDING = 0
    LOADING = 1
    ACTIVE = 2
    FAILED = 3
    DISPOSED = 4
    UNLOADING = 5


class CordisError(Exception):
    def __init__(self, code: str, message: Optional[str] = None):
        self.code = code
        super().__init__(message or code)


class ValidationError(TypeError):
    def __init__(self, issues: List[Any]):
        lines = []
        for issue in issues:
            if isinstance(issue, dict):
                message = issue.get("message", str(issue))
                path = issue.get("path")
                if path:
                    message += " (at %s)" % ".".join(str(item) for item in path)
            else:
                message = str(issue)
            lines.append("  - " + message)
        super().__init__("invalid config:\n" + "\n".join(lines))


class DisposalError(Exception):
    """All cleanup failures produced by one compound effect."""

    def __init__(self, errors: List[BaseException]):
        self.errors = errors
        super().__init__("; ".join(str(error) for error in errors))


def resolve_config(plugin: Any, config: Any) -> Any:
    schema = getattr(plugin, "schema", None) or getattr(plugin, "Config", None)
    if not schema:
        return config
    validate = getattr(schema, "validate", None)
    if not callable(validate):
        return config
    result = validate(config)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError("Async config validation is not supported")
    if isinstance(result, dict) and result.get("issues"):
        raise ValidationError(result["issues"])
    return result.get("value", config) if isinstance(result, dict) else config


def _start_awaitable(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value

    async def settle() -> Any:
        return await value

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(settle())
    if isinstance(value, asyncio.Future):
        return value
    if inspect.iscoroutine(value):
        return loop.create_task(value)
    return loop.create_task(settle())


class EffectMeta:
    def __init__(self, label: str, children: Optional[List["EffectMeta"]] = None):
        self.label = label
        self.children = children or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "children": [child.to_dict() for child in self.children],
        }


class _EffectDisposer:
    def __init__(self, owner: "Fiber", label: str):
        self.owner = owner
        self.meta = EffectMeta(label)
        self.disposables: List[Callable[[], Any]] = []
        self.setup_task: Optional[asyncio.Future] = None
        self.remove: Callable[[], bool] = lambda: False
        self.disposing = False
        self.disposal_task: Optional[asyncio.Future] = None
        self.setup_error: Optional[BaseException] = None
        self.auto_disposal = False

    def collect(self, value: Any) -> None:
        if value is None:
            return
        if not callable(value):
            raise TypeError("Invalid effect")
        self.disposables.append(value)
        self.owner._disposables.delete(value)
        child_meta = getattr(value, "meta", None)
        if child_meta is not None:
            self.meta.children.append(child_meta)

    async def consume_async(self, result: Any) -> None:
        if inspect.isawaitable(result):
            self.collect(await result)
            return
        async for value in result:
            self.collect(value)

    async def wait_setup(self) -> "_EffectDisposer":
        if self.setup_task is not None:
            await asyncio.shield(self.setup_task)
        return self

    def __await__(self):
        return self.wait_setup().__await__()

    async def _dispose_async(self) -> None:
        errors: List[BaseException] = []
        setup_cancelled = False
        if self.setup_task is not None:
            try:
                await asyncio.shield(self.setup_task)
            except asyncio.CancelledError:
                setup_cancelled = True
            except Exception as error:
                errors.append(error)
        while self.disposables:
            disposable = self.disposables.pop()
            try:
                result = disposable()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError:
                setup_cancelled = True
            except Exception as error:
                errors.append(error)
        self.remove()
        if setup_cancelled:
            raise asyncio.CancelledError()
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise DisposalError(errors)

    async def _observe_auto_disposal(self) -> None:
        try:
            if self.disposal_task is not None:
                await asyncio.shield(self.disposal_task)
        except asyncio.CancelledError:
            raise
        except DisposalError as aggregate:
            for error in aggregate.errors:
                if error is not self.setup_error:
                    self.owner._log_error(error)
        except Exception as error:
            if error is not self.setup_error:
                self.owner._log_error(error)

    def setup_done(self, task: asyncio.Future) -> None:
        if task.cancelled():
            self.start_disposal()
            return
        error = task.exception()
        if error is None:
            return
        self.setup_error = error
        self.auto_disposal = True
        self.start_disposal()
        asyncio.get_running_loop().create_task(self._observe_auto_disposal())

    async def _finish_failed_setup_rollback(
        self,
        first: Any,
        errors: List[BaseException],
        cancelled: bool,
    ) -> None:
        current = first
        try:
            while True:
                try:
                    await current
                except asyncio.CancelledError:
                    cancelled = True
                except Exception as error:
                    errors.append(error)

                current = None
                while self.disposables:
                    try:
                        result = self.disposables.pop()()
                        if inspect.isawaitable(result):
                            current = result
                            break
                    except asyncio.CancelledError:
                        cancelled = True
                    except Exception as error:
                        errors.append(error)
                if current is None:
                    break
        finally:
            self.remove()
        for error in errors:
            self.owner._log_error(error)
        if cancelled:
            raise asyncio.CancelledError()

    def rollback_failed_setup(self) -> None:
        errors: List[BaseException] = []
        cancelled = False
        while self.disposables:
            try:
                result = self.disposables.pop()()
                if inspect.isawaitable(result):
                    self.disposing = True
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        asyncio.run(self._finish_failed_setup_rollback(
                            result, errors, cancelled
                        ))
                    else:
                        self.disposal_task = loop.create_task(
                            self._finish_failed_setup_rollback(
                                result, errors, cancelled
                            )
                        )
                    return
            except asyncio.CancelledError:
                cancelled = True
            except Exception as error:
                errors.append(error)
        self.remove()
        for error in errors:
            self.owner._log_error(error)
        if cancelled:
            raise asyncio.CancelledError()

    def start_disposal(self) -> None:
        if not self.disposing:
            self.disposing = True
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._dispose_async())
            else:
                self.disposal_task = loop.create_task(self._dispose_async())

    def __call__(self):
        self.start_disposal()

        async def join() -> None:
            if self.disposal_task is not None:
                await asyncio.shield(self.disposal_task)

        return join()


INACTIVE_EPOCH = "__INACTIVE__"


class Fiber:
    _uid_counter = 0

    def __init__(self, parent_ctx: Any, plugin: Any, config: Any = None, runtime: Any = None):
        self.parent = parent_ctx
        self.plugin = plugin
        self.runtime = runtime
        self._config = config
        self.config = config
        self.store: Optional[Dict[str, Any]] = {}
        self.inertia: Optional[asyncio.Future] = None
        self.epoch = INACTIVE_EPOCH
        self._error: Optional[BaseException] = None
        self._store: Dict[str, Any] = {}
        self._disposables: DisposableList[Callable[[], Any]] = DisposableList()
        self._dispose_task: Optional[asyncio.Future] = None
        self._restart_task: Optional[asyncio.Future] = None
        self._dispose_requested = False

        if runtime is not None:
            if hasattr(parent_ctx, "registry"):
                self.uid = parent_ctx.registry.counter
            else:
                Fiber._uid_counter += 1
                self.uid = Fiber._uid_counter
            self.ctx = parent_ctx.extend({"fiber": self}) if parent_ctx else None
            self.state = FiberState.PENDING
        else:
            self.uid = 0
            self.ctx = parent_ctx
            self.state = FiberState.ACTIVE

    @property
    def name(self) -> str:
        if self.runtime is not None and getattr(self.runtime, "name", None):
            return self.runtime.name
        if self.plugin:
            return (getattr(self.plugin, "name", None)
                    or getattr(self.plugin, "id", None)
                    or getattr(self.plugin, "__name__", None)
                    or self.plugin.__class__.__name__)
        return "root"

    def assert_active(self) -> None:
        if self.uid is None or self.state in (FiberState.DISPOSED, FiberState.UNLOADING):
            raise CordisError("INACTIVE_EFFECT", "cannot create effect on inactive context")

    def _log_error(self, reason: BaseException) -> None:
        logger = None
        if self.ctx is not None:
            try:
                logger = self.ctx.get("logger", None, strict=False)
            except (AttributeError, TypeError):
                logger = None
        if logger is not None and callable(getattr(logger, "error", None)):
            logger.error(reason)
        else:
            print("[Cordis Fiber Error] %s" % reason, file=sys.stderr)

    def effect(self, execute: Callable[[], Any], label: str = "anonymous") -> _EffectDisposer:
        self.assert_active()
        if self.state == FiberState.UNLOADING:
            raise CordisError("INACTIVE_EFFECT", "cannot create effect on inactive context")
        if not callable(execute):
            raise TypeError("Invalid effect")

        wrapper = _EffectDisposer(self, label or "anonymous")
        wrapper.remove = self._disposables.push(wrapper)
        try:
            result = execute()
            if callable(result) or result is None:
                wrapper.collect(result)
            elif inspect.isawaitable(result) or hasattr(result, "__aiter__"):
                loop = asyncio.get_running_loop()
                wrapper.setup_task = loop.create_task(wrapper.consume_async(result))
                wrapper.setup_task.add_done_callback(wrapper.setup_done)
            elif isinstance(result, Iterable) and not isinstance(result, (str, bytes, dict)):
                for disposable in result:
                    wrapper.collect(disposable)
            else:
                raise TypeError("Invalid effect")
        except BaseException:
            wrapper.rollback_failed_setup()
            raise
        return wrapper

    def get_effects(self) -> List[Dict[str, Any]]:
        return [
            disposable.meta.to_dict()
            for disposable in self._disposables
            if isinstance(disposable, _EffectDisposer)
        ]

    def set_state(self, new_state: int) -> None:
        old_state = self.state
        if old_state == new_state:
            return
        self.state = new_state
        if self.ctx is not None and hasattr(self.ctx, "emit"):
            self.ctx.emit("internal/status", self, old_state)

    def set_epoch(self, epoch: str) -> None:
        old_epoch = self.epoch
        if epoch == old_epoch:
            return
        self.epoch = epoch
        if self.inertia is not None:
            return
        if epoch != INACTIVE_EPOCH and old_epoch == INACTIVE_EPOCH:
            self._begin_reload(epoch)
        else:
            self._begin_unload()

    def _begin_reload(self, epoch: str) -> None:
        self.set_state(FiberState.LOADING)
        self.inertia = asyncio.get_running_loop().create_task(self._reload(epoch))

    def _begin_unload(self) -> None:
        self.set_state(FiberState.UNLOADING)
        self.inertia = asyncio.get_running_loop().create_task(self._unload())

    def _resolve_config(self, config: Any) -> Any:
        if hasattr(self.ctx, "waterfall_sync"):
            config = self.ctx.waterfall_sync(
                "internal/config", config, lambda *_args: config
            )
        return resolve_config(self.plugin, config) if self.runtime else config

    async def _reload(self, expected_epoch: str) -> None:
        self.store = dict(self._store)
        try:
            await asyncio.sleep(0)
            if self.epoch == expected_epoch:
                self.config = self._resolve_config(self._config)
                setup = self.effect(
                    lambda: invoke_plugin(self.plugin, self.ctx, self.config),
                    "plugin(%s)" % self.name,
                )
                await setup
                self._error = None
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._log_error(error)
            self._error = error
            self.epoch = INACTIVE_EPOCH
        if self.epoch == expected_epoch:
            self.inertia = None
            self.set_state(FiberState.ACTIVE)
        else:
            self.set_state(FiberState.UNLOADING)
            self.inertia = asyncio.get_running_loop().create_task(self._unload())

    async def _run_disposables(self) -> None:
        disposables = self._disposables.clear()
        results = await asyncio.gather(
            *(self._call_disposer(disposable) for disposable in disposables),
            return_exceptions=True
        )
        cancelled = False
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                cancelled = True
            elif isinstance(result, Exception):
                if isinstance(result, DisposalError):
                    for error in result.errors:
                        self._log_error(error)
                else:
                    self._log_error(result)
        if cancelled:
            raise asyncio.CancelledError()

    async def _call_disposer(self, disposer: Callable[[], Any]) -> None:
        try:
            result = disposer()
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception:
            if isinstance(disposer, _EffectDisposer) and disposer.auto_disposal:
                return
            raise

    async def _unload(self) -> None:
        cancelled = False
        try:
            await self._run_disposables()
        except asyncio.CancelledError:
            cancelled = True
        finally:
            self.store = None
            if self.epoch == INACTIVE_EPOCH:
                self.inertia = None
                if self.uid is None:
                    self.set_state(FiberState.DISPOSED)
                elif self._error is not None:
                    self.set_state(FiberState.FAILED)
                else:
                    self.set_state(FiberState.PENDING)
            else:
                epoch = self.epoch
                self.set_state(FiberState.LOADING)
                self.inertia = asyncio.get_running_loop().create_task(self._reload(epoch))
        if cancelled:
            raise asyncio.CancelledError()

    async def wait(self) -> "Fiber":
        while self.inertia is not None:
            await asyncio.shield(self.inertia)
        if self._error is not None:
            raise self._error
        return self

    def __await__(self):
        return self.wait().__await__()

    async def _dispose_impl(self) -> None:
        self.set_epoch(INACTIVE_EPOCH)
        while self.inertia is not None:
            await asyncio.shield(self.inertia)
        await self._run_disposables()
        self.store = None
        self.uid = None
        self.set_state(FiberState.DISPOSED)
        if self.runtime is not None and hasattr(self.runtime, "remove_fiber"):
            self.runtime.remove_fiber(self)
        if self.ctx is not None and hasattr(self.ctx, "emit"):
            self.ctx.emit("internal/plugin", self)

    async def dispose(self) -> None:
        if self.runtime is None:
            await self._run_disposables()
            return
        self._dispose_requested = True
        if self._dispose_task is None or self._dispose_task.done():
            self._dispose_task = asyncio.get_running_loop().create_task(self._dispose_impl())
        await asyncio.shield(self._dispose_task)

    async def _restart_impl(self) -> None:
        self._error = None
        self.set_epoch(INACTIVE_EPOCH)
        self.set_epoch("active_epoch")
        await self.wait()

    async def restart(self, new_config: Optional[Any] = None) -> None:
        if self._restart_task is not None and not self._restart_task.done():
            await asyncio.shield(self._restart_task)
            return
        self.assert_active()
        if new_config is not None:
            self._config = new_config
        self._restart_task = asyncio.get_running_loop().create_task(self._restart_impl())
        await asyncio.shield(self._restart_task)

    def update(self, config: Any, no_save: bool = False) -> Any:
        self.assert_active()
        self._config = config
        if self.state != FiberState.ACTIVE:
            self._error = None
            self.set_epoch(INACTIVE_EPOCH)
            self.ctx.registry.refresh_fiber(self)
            return None
        config = self._resolve_config(config)

        def apply_update(*_args: Any) -> Any:
            self.config = config
            self._error = None
            return _start_awaitable(self.restart())

        if hasattr(self.ctx, "waterfall_sync"):
            result = self.ctx.waterfall_sync(
                "internal/update", config, no_save, apply_update
            )
            return _start_awaitable(result)
        return apply_update()

    def __repr__(self) -> str:
        return "<Fiber %s state=%s>" % (self.name, self.state)
