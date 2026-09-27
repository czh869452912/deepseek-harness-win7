"""Transactional loader entry translated from vendor/loader config/entry.ts."""

import asyncio
import copy
import inspect
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin, invoke_plugin
from dsh.cordis.registry import Inject


def _sorted_options(options: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in ("id", "name"):
        if key in options:
            result[key] = options[key]
    for key in sorted(options):
        if key not in ("id", "name", "config"):
            result[key] = options[key]
    if "config" in options:
        result["config"] = options["config"]
    return result


def _replace_keys(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    target.clear()
    target.update(source)
    return target


def _inherited_value(ctx: Any, name: str) -> Any:
    current = ctx
    while current is not None:
        if name in current.__dict__:
            return current.__dict__[name]
        current = getattr(current, "_parent", None)
    return None


def _update_error(stage: str, options: Dict[str, Any], cause: BaseException) -> RuntimeError:
    error = RuntimeError(
        "failed to %s loader entry %s (%s): %s" % (
            stage, options.get("id"), options.get("name"), cause,
        )
    )
    error.__cause__ = cause
    return error


def _rollback_error(*errors: BaseException) -> BaseException:
    from dsh.cordis.loader_group import LoaderAggregateError

    return LoaderAggregateError(list(errors), "loader entry rollback failed")


class _CallablePlugin(Plugin):
    def __init__(self, callback: Any, config: Any, inject: Any):
        super().__init__(config if isinstance(config, dict) else {})
        self.callback = callback
        self.raw_config = config
        self.inject = inject
        self.name = getattr(callback, "name", None) or getattr(callback, "__name__", "loaded-plugin")

    def apply(self, ctx: Any) -> Any:
        return invoke_plugin(self.callback, ctx, self.raw_config)


class _EntryRuntimePlugin(Plugin):
    def __init__(self, entry: Any, plugin: Any, config: Any, inject: Any):
        super().__init__({})
        self.entry = entry
        self.plugin = plugin
        self.raw_config = config
        self.inject = inject
        self.id = entry.id
        self.name = getattr(plugin, "name", None) or getattr(plugin, "__name__", "loaded-plugin")

    def apply(self, ctx: Any) -> Any:
        def resolve_config(config: Any, next_fn: Any) -> Any:
            value = next_fn()
            if self.entry.options.get("group"):
                return value
            return self.entry.loader.interpolate(ctx, value)

        async def persist_update(config: Any, no_save: bool, next_fn: Any) -> Any:
            result = next_fn()
            if inspect.isawaitable(result):
                result = await result
            if not no_save:
                self.entry.options["config"] = config
                write_result = self.entry.parent.tree.write()
                if inspect.isawaitable(write_result):
                    await write_result
            return result

        ctx.on("internal/config", resolve_config)
        ctx.on("internal/update", persist_update, prepend=True)
        runtime_config = getattr(ctx.fiber, "config", self.raw_config)
        if getattr(self.plugin, "_cordis_entry_group", False):
            if isinstance(runtime_config, list):
                self.plugin.rows = runtime_config
        else:
            runtime_config = self.entry.loader.interpolate(ctx, runtime_config)
            if isinstance(self.plugin, Plugin):
                self.plugin.config = runtime_config
        if isinstance(self.plugin, _CallablePlugin):
            return invoke_plugin(self.plugin.callback, ctx, runtime_config)
        return invoke_plugin(self.plugin, ctx, runtime_config)


class Entry:
    key = "_loader_entry"

    def __init__(self, loader: Any, base_ctx: Optional[Any] = None):
        self.loader = loader
        self.ctx = (base_ctx or loader.ctx).extend({self.key: self})
        self.fiber: Optional[Any] = None
        self.parent: Any = None
        self.options: Dict[str, Any] = {}
        self.subgroup: Optional[Any] = None
        self.subtree: Optional[Any] = None
        self.realm: Optional[Any] = None
        self._init_task: Optional[Any] = None
        self._disposing = 0
        self._plugin_source: Any = None
        self.context.emit("loader/entry-init", self)

    @property
    def context(self) -> Any:
        return self.ctx

    @property
    def id(self) -> str:
        local = self.options.get("id", "")
        owner = getattr(self.parent, "owner_entry", None) if self.parent is not None else None
        return "%s:%s" % (owner.id, local) if owner is not None else local

    @property
    def name(self) -> Optional[str]:
        return self.options.get("name")

    @property
    def config(self) -> Any:
        return self.options.get("config", {})

    @property
    def disabled(self) -> bool:
        return self._disabled(self.options)

    def disabled_of(self, options: Dict[str, Any]) -> bool:
        value = options.get("disabled")
        if self.loader.is_js_expr(value):
            return bool(self.evaluate(value["__jsExpr"]))
        return bool(value)

    def _disabled(self, options: Dict[str, Any]) -> bool:
        if options.get("group"):
            return False
        if self.disabled_of(options):
            return True
        owner = getattr(self.parent, "owner_entry", None) if self.parent is not None else None
        while owner is not None:
            if owner.disabled_of(owner.options):
                return True
            owner = getattr(owner.parent, "owner_entry", None)
        return False

    def evaluate(self, expression: str) -> Any:
        return self.loader.evaluate(self.ctx, expression)

    def get_outer_stack(self) -> List[str]:
        entry: Optional[Any] = self
        result = []
        while entry is not None:
            result.append("    at %s#%s" % (
                getattr(entry.parent.tree.ctx, "baseUrl", ""),
                entry.options.get("id", ""),
            ))
            entry = getattr(entry.parent, "owner_entry", None)
        return result

    getOuterStack = get_outer_stack

    async def _patch_context(self, diff: List[str]) -> None:
        async def apply_patch(*_args: Any) -> None:
            parent_ctx = self.parent.ctx
            self.ctx._parent = parent_ctx
            base_url = _inherited_value(parent_ctx, "baseUrl")
            self.ctx.baseUrl = base_url
            if self.fiber is not None:
                self.fiber.ctx._parent = self.ctx
                self.fiber.ctx.baseUrl = base_url
            if self.fiber is not None and self.fiber.uid is not None and (
                    "config" in diff or self.options.get("group")):
                value = self.fiber.update(self.options.get("config", {}), no_save=True)
                if inspect.isawaitable(value):
                    await value
                await self.fiber

        await self.context.waterfall("loader/patch-context", self, apply_patch)

    def _runtime_config(self) -> Any:
        if self.options.get("group"):
            return self.options.get("config", [])
        return self.loader.interpolate(self.ctx, self.options.get("config", {}))

    async def refresh(self) -> None:
        if self.fiber is None and not self.disabled:
            await self.init()

    async def _dispose(self, fiber: Optional[Any] = None) -> None:
        target = fiber or self.fiber
        if target is None:
            return
        if self.fiber is target:
            self.fiber = None
        self._disposing += 1
        try:
            await target.dispose()
        finally:
            self._disposing -= 1

    async def update(self, options: Dict[str, Any], create: bool = False,
                     force: bool = False) -> None:
        previous_options = self.options
        legacy = copy.deepcopy(previous_options)
        if create:
            candidate = _sorted_options(dict(options))
            options.clear()
            options.update(candidate)
            candidate = options
        else:
            candidate = dict(previous_options)
            for key, value in options.items():
                if value is None:
                    candidate.pop(key, None)
                else:
                    candidate[key] = value
            candidate = _sorted_options(candidate)
        diff = [key for key in set(candidate) | set(previous_options)
                if candidate.get(key) != previous_options.get(key)]
        if not diff and not force:
            return

        def commit() -> None:
            if create:
                return
            self.options = _replace_keys(previous_options, candidate)

        previous_fiber = self.fiber
        previous_plugin = self._plugin_source
        if previous_fiber is None or previous_fiber.uid is None:
            self.fiber = None
            self.options = candidate
            try:
                if not self._disabled(candidate):
                    await self.init()
            except BaseException:
                self.options = previous_options
                raise
            commit()
            return

        if self._disabled(candidate):
            self.options = candidate
            try:
                await self._dispose(previous_fiber)
            except BaseException as error:
                self.options = previous_options
                raise _update_error("dispose", candidate, error)
            commit()
            self.context.emit("loader/partial-dispose", self, legacy, True)
            return

        replace = any(key in diff for key in ("name", "inject", "group"))
        if not replace:
            self.options = candidate
            try:
                await self._patch_context(diff)
            except BaseException as error:
                self.options = previous_options
                try:
                    await self._patch_context(diff)
                except BaseException as rollback_error:
                    raise _update_error(
                        "rollback", legacy, _rollback_error(error, rollback_error)
                    )
                self.context.emit("loader/partial-dispose", self, candidate, True)
                raise _update_error("apply", candidate, error)
            commit()
            self.context.emit("loader/partial-dispose", self, legacy, True)
            return

        try:
            plugin = self.loader.import_plugin(candidate["name"])
        except BaseException as error:
            raise _update_error("import", candidate, error)
        self.options = candidate
        try:
            await self._dispose(previous_fiber)
        except BaseException as error:
            self.options = previous_options
            raise _update_error("dispose", candidate, error)
        try:
            await self._start(plugin)
        except BaseException as error:
            self.options = previous_options
            try:
                await self._start(previous_plugin)
            except BaseException as rollback_error:
                raise _update_error(
                    "rollback", legacy, _rollback_error(error, rollback_error)
                )
            self.context.emit("loader/partial-dispose", self, candidate, True)
            raise _update_error("apply", candidate, error)
        commit()
        self.context.emit("loader/partial-dispose", self, legacy, True)

    async def init(self) -> None:
        if self._init_task is None:
            self._init_task = asyncio.ensure_future(self._init())
        try:
            await self._init_task
        finally:
            self._init_task = None
            if not self.loader.get_tasks():
                self.ctx.reflect.notify(["loader"])
        await self._await_fiber()

    async def _await_fiber(self) -> None:
        if self.fiber is None:
            return
        try:
            await self.fiber
        except BaseException as error:
            raise _update_error("apply", self.options, error)

    async def _init(self) -> None:
        try:
            plugin = self.loader.import_plugin(self.options["name"])
        except BaseException as error:
            raise _update_error("import", self.options, error)
        try:
            await self._start(plugin)
        except BaseException as error:
            raise _update_error("apply", self.options, error)

    def _materialize(self, plugin: Any) -> Any:
        runtime_config = self.options.get("config", {})
        declared = Inject.resolve(getattr(plugin, "inject", None))
        Inject.resolve(self.options.get("inject"), declared)
        if inspect.isclass(plugin) and issubclass(plugin, Plugin):
            target = plugin(config=runtime_config)
        elif inspect.isclass(plugin):
            try:
                target = plugin()
            except TypeError:
                target = _CallablePlugin(plugin, runtime_config, declared)
        elif isinstance(plugin, Plugin):
            target = plugin
            target.config = runtime_config
        else:
            target = _CallablePlugin(plugin, runtime_config, declared)
        return _EntryRuntimePlugin(self, target, runtime_config, declared)

    async def _start(self, plugin: Any) -> None:
        fiber = None
        try:
            await self._patch_context([])
            materialized = self._materialize(plugin)
            registry_config = None if self.options.get("group") else self.options.get("config", {})
            fiber = self.ctx.registry.plugin(
                materialized, config=registry_config, parent_ctx=self.ctx
            )
            raw_update = fiber.update

            async def update(config: Any, no_save: bool = False) -> Any:
                result = raw_update(config, no_save)
                if inspect.isawaitable(result):
                    return await result
                return result

            fiber.update = update
            fiber.entry = self
            self.fiber = fiber
            self._plugin_source = plugin
            await fiber
        except BaseException:
            await self._dispose(fiber)
            raise

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.options)


EntryNode = Entry


__all__ = ["Entry", "EntryNode"]
