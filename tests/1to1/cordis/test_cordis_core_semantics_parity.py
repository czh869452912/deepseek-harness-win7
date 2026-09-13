"""Cordis core semantics parity suite.

Every case below is mapped to the pinned reference source
(``reference/vendor/cordis/src/*``) and to the executable oracle runs recorded
for this unit (both implementations observed through the same scenario).

- C1  fiber.ts `_execute`: `typeof effect === 'function'` is tested *before*
      `'then' in effect`, so a returned disposer that is also thenable (for
      example the wrapper from `ctx.provide()` / `ctx.effect()`) is collected as
      an effect instead of being awaited and torn down.
- C2  fiber.ts `_execute`: `Promise<Disposable>` is accepted and awaited.
- C3  reflect.ts `ReflectService.get(name, strict = true)` returns nothing for an
      implementation whose providing fiber is not ACTIVE; the proxy path for a
      runtime-less (root) context reads non-strictly (`reflect.get(prop, false)`).
- C4  fiber.ts `_checkImpl` / `_refresh`: a PENDING consumer activates when the
      injected service becomes available and unloads when it goes away.
- C5  fiber.ts `_updateState`: the `internal/status` sequence for a dependency
      loss is (fiber, oldState) pairs on every real transition.
- C6  fiber.ts `dispose` comment: a PENDING fiber that already owns effects
      (registered by an `internal/plugin` observer) drains them before disposal
      reports completion.
- C7  events.ts built-in `internal/listener` / `internal/update` handlers: a
      fiber-scoped `internal/update` listener is chained through the fiber's
      `_hooks` list, and not calling `next()` vetoes the restart.
- C8  reflect.ts `ReflectService.handler.get`: `internal/get` dispatches for
      plugin-fiber proxy reads, not for `reflect.get()` itself.
- C9  events.ts `EventsService.register` / fiber.ts `getEffects`.
- C10 fiber.ts `effect` `collect`: a nested effect is owned by its collector and
      its `EffectMeta` nests under the collector's.
- C11 fiber.ts `_execute` / `getEffects`: a plain function result is collected on
      the fiber and reports no metadata.
- C12 reflect.ts `provide` disposer ordering (unregister, notify, await woken
      fibers, then drop the providing fiber's own store entry).
- C13 fiber.ts `dispose`: the async body starts at the call site.
- C14 fiber.ts `_reload`: a load invalidated before its first checkpoint never
      runs the plugin body.
- C15 fiber.ts `_execute` iterable branch: yielded disposers are collected on the
      fiber without metadata.
- C16 fiber.ts `effect` wrapper `then`/`disposeAfter`: awaiting the public
      disposer waits for async setup and propagates its failure; calling the
      disposer while setup is in flight reraises the same reason.
- C17 context.ts `extend`/`intercept` and service.ts `resolveConfig`: the
      intercept map is inherited through the context chain, so each ancestor
      level contributes exactly one merge input, root first.
- C18 events.ts `EventsService.parallel`: resolves with no value and raises
      `AggregateError` when listeners fail.
- C19 events.ts `EventsService.bail`: synchronous dispatch returning the first
      bail value, without awaiting the remaining listeners.
- C20 fiber.ts `_execute` asyncIterator branch: disposers from an async-iterable
      plugin body are collected on the fiber without metadata.
- C21 reflect.ts `ReflectService.get(name, strict = true)`: the second positional
      parameter of `ctx.get` selects strict resolution.
"""

import asyncio
import inspect

import pytest

from dsh.cordis.context import Context
from dsh.cordis.events import AggregateError
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


class _ApplyPlugin(Plugin):
    """Object plugin whose `apply` body is supplied per case."""

    def __init__(self, name: str, body, **attrs):
        self.name = name
        self._body = body
        for key, value in attrs.items():
            setattr(self, key, value)

    def apply(self, ctx, config=None):
        try:
            sig = inspect.signature(self._body)
            params = list(sig.parameters.values())
            positional = len([p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
            varargs = any(p.kind == p.VAR_POSITIONAL for p in params)
        except (ValueError, TypeError):
            positional, varargs = 1, False
        if positional >= 2 or varargs:
            return self._body(ctx, config)
        return self._body(ctx)


@pytest.mark.asyncio
async def test_c1_returned_thenable_disposer_is_collected_not_awaited():
    """C1: `apply` returning a callable-and-awaitable disposer keeps the service alive.

    Reference: fiber.ts `_execute` collects functions before inspecting `then`.
    """
    ctx = Context()

    def body(c):
        # `ctx.provide()` returns the effect wrapper: callable *and* thenable.
        return c.provide("kept", {"v": 1})

    fiber = await ctx.plugin(_ApplyPlugin("provided", body))

    # Awaiting the returned wrapper would have disposed the registration during
    # activation; the reference keeps it, so the service is visible and ACTIVE.
    assert fiber.state == FiberState.ACTIVE
    assert ctx.get("kept") == {"v": 1}

    await fiber.dispose()
    assert ctx.get("kept") is None
    assert "kept" not in ctx.reflect.store


@pytest.mark.asyncio
async def test_c2_apply_returning_promise_of_disposer_owns_it():
    """C2: `apply` may return a promise of a disposer; activation awaits it."""
    ctx = Context()
    order = []

    async def body(c):
        await asyncio.sleep(0)
        order.append("setup")
        return lambda: order.append("dispose")

    fiber = await ctx.plugin(_ApplyPlugin("async-effect", body))
    assert fiber.state == FiberState.ACTIVE
    assert order == ["setup"]

    await fiber.dispose()
    assert order == ["setup", "dispose"]


@pytest.mark.asyncio
async def test_c3_strict_get_ignores_inactive_provider():
    """C3: strict `ctx.get` sees only ACTIVE providers; loose/attribute reads differ."""
    ctx = Context()

    async def body(c):
        c.provide("lazy", "value")
        await asyncio.sleep(0.03)

    fiber = ctx.plugin(_ApplyPlugin("loading-provider", body))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert fiber.state == FiberState.LOADING
    # reflect.ts `_getImpl(name, strict = true)` filters on `fiber.state`.
    assert ctx.get("lazy") is None
    # Non-strict read (and the runtime-less proxy path) observe the value.
    assert ctx.reflect.get(ctx, "lazy", strict=False) == "value"
    assert getattr(ctx, "lazy") == "value"

    await fiber.await_settled()
    assert ctx.get("lazy") == "value"


@pytest.mark.asyncio
async def test_c4_pending_consumer_activates_when_dependency_provided():
    """C4: injected dependencies drive LOADING/UNLOADING through composite epochs."""
    ctx = Context()
    log = []

    def consumer_body(c):
        log.append("apply")
        return lambda: log.append("dispose")

    consumer = _ApplyPlugin("consumer", consumer_body, inject=["svc"])
    fiber = ctx.plugin(consumer)
    assert fiber.state == FiberState.PENDING

    provider = _ApplyPlugin("provider", lambda c: c.provide("svc", {"v": 1}))
    provider_fiber = await ctx.plugin(provider)
    await fiber.await_settled()

    assert fiber.state == FiberState.ACTIVE
    assert fiber.ctx.svc == {"v": 1}
    assert log == ["apply"]

    await provider_fiber.dispose()
    await fiber.await_settled()

    assert log == ["apply", "dispose"]
    assert fiber.state == FiberState.PENDING
    assert ctx.get("svc") is None


@pytest.mark.asyncio
async def test_c5_status_sequence_for_dependency_loss():
    """C5: `internal/status` reports (fiber, oldState) for every real transition."""
    ctx = Context()
    sequence = []
    ctx.on("internal/status", lambda fiber, old: sequence.append([old, fiber.state]))

    provider_fiber = await ctx.plugin(_ApplyPlugin("prov", lambda c: c.provide("seq-svc", 1)))
    consumer_fiber = ctx.plugin(_ApplyPlugin("cons", lambda c: None, inject=["seq-svc"]))
    await consumer_fiber.await_settled()

    await provider_fiber.dispose()
    await consumer_fiber.await_settled()

    assert sequence == [
        [FiberState.PENDING, FiberState.LOADING],
        [FiberState.LOADING, FiberState.ACTIVE],
        [FiberState.PENDING, FiberState.LOADING],
        [FiberState.LOADING, FiberState.ACTIVE],
        [FiberState.ACTIVE, FiberState.UNLOADING],
        [FiberState.ACTIVE, FiberState.UNLOADING],
        [FiberState.UNLOADING, FiberState.PENDING],
        [FiberState.UNLOADING, FiberState.DISPOSED],
    ]


@pytest.mark.asyncio
async def test_c6_dispose_drains_effects_registered_on_pending_fiber():
    """C6: a PENDING fiber's pre-activation effects are torn down by `dispose()`."""
    ctx = Context()
    log = []

    def on_plugin(fiber):
        if fiber.name == "pending-owner":
            fiber.ctx.effect(lambda: (lambda: log.append("drained")), "observer")

    ctx.on("internal/plugin", on_plugin)
    fiber = ctx.plugin(_ApplyPlugin("pending-owner", lambda c: log.append("should-not-run"), inject=["never"]))

    assert fiber.state == FiberState.PENDING
    await fiber.dispose()

    assert log == ["drained"]
    assert fiber.state == FiberState.DISPOSED


@pytest.mark.asyncio
async def test_c8_internal_get_dispatches_only_for_proxy_reads():
    """C8: `internal/get` runs for plugin-fiber proxy reads only.

    Reference: reflect.ts `ReflectService.handler.get` returns
    `ctx.reflect.get(prop, false)` for a runtime-less context and dispatches the
    waterfall otherwise; `ReflectService.get()` itself never dispatches.
    """
    ctx = Context()
    dispatched = []

    def on_get(target_ctx, name, error, next_fn):
        dispatched.append(name)
        if name == "virtual":
            return "intercepted"
        return next_fn()

    ctx.on("internal/get", on_get)
    ctx.provide("declared", "value")

    # Root (runtime-less) context: no dispatch, and `ctx.get` never dispatches.
    assert ctx.get("declared") == "value"
    assert dispatched == []

    seen = {}

    class ReaderPlugin(Plugin):
        name = "internal-get-reader"
        inject = ["declared"]

        def apply(self, c):
            seen["attribute"] = c.declared
            seen["virtual"] = c.virtual
            seen["via_get"] = c.get("declared")

    await ctx.plugin(ReaderPlugin)

    assert seen == {"attribute": "value", "virtual": "intercepted", "via_get": "value"}
    assert dispatched == ["declared", "virtual"]


@pytest.mark.asyncio
async def test_c7_fiber_scoped_internal_update_hook_chain():
    """C7: fiber-scoped `internal/update` hooks chain (config, noSave, next) and veto."""
    ctx = Context()
    log = []

    def body(c, config=None):
        log.append("apply:" + repr(config))

        def hook(cfg, no_save=False, next_fn=None, *rest):
            log.append("hook:" + repr(cfg) + ":" + repr(no_save))
            return next_fn()

        c.on("internal/update", hook)
        return lambda: log.append("dispose")

    fiber = await ctx.plugin(_ApplyPlugin("upd-scope", body), {"a": 1})
    # The hook is chained through the fiber's own `internal/update` list
    # (events.ts `internal/listener` handler), not a bus-level listener.
    assert len(fiber._hooks["internal/update"]) == 1

    result = fiber.update({"a": 2})
    if result is not None and hasattr(result, "__await__"):
        await result
    await fiber.await_settled()

    assert log == ["apply:{'a': 1}", "hook:{'a': 2}:False", "dispose", "apply:{'a': 2}"]
    assert fiber.state == FiberState.ACTIVE

    # A hook that never calls `next()` vetoes the restart: the earlier hook runs,
    # the chain stops at the veto, and no apply/dispose follows.
    veto_log = []

    def veto(cfg, no_save=False, next_fn=None, *rest):
        veto_log.append("veto")
        return None

    fiber.ctx.on("internal/update", veto)
    applied_before_veto = log.count("apply:{'a': 2}")
    result = fiber.update({"a": 3})
    if result is not None and hasattr(result, "__await__"):
        await result
    await fiber.await_settled()

    assert veto_log == ["veto"]
    assert fiber.state == FiberState.ACTIVE
    assert fiber.config == {"a": 2}
    assert log.count("apply:{'a': 2}") == applied_before_veto

@pytest.mark.asyncio
async def test_c9_ctx_on_registers_one_labeled_effect():
    """C9: `ctx.on` adds one effect labeled `ctx.on("name")`; its disposer removes it.

    Reference: events.ts `EventsService.register` returns the fiber effect
    wrapper (label `ctx.on("...")`), and fiber.ts `getEffects` reports live
    effects by label. `ctx.effect()` with no label keeps the fiber default.
    """
    ctx = Context()
    disposer = ctx.on("c9-evt", lambda: None)
    assert [effect["label"] for effect in ctx.fiber.get_effects()] == ['ctx.on("c9-evt")']

    # The returned object is the fiber effect wrapper, so calling it reports the
    # disposer result (`undefined` for a synchronous listener removal) and is
    # single-shot.
    assert disposer() is None
    assert ctx.fiber.get_effects() == []
    assert disposer() is None

    once_disposer = ctx.once("c9-evt", lambda: None)
    assert [effect["label"] for effect in ctx.fiber.get_effects()] == ['ctx.on("c9-evt")']
    once_disposer()

    ctx.effect(lambda: None)
    assert [effect["label"] for effect in ctx.fiber.get_effects()] == ["anonymous"]


@pytest.mark.asyncio
async def test_c10_effect_takes_ownership_of_nested_effect():
    """C10: an effect that collects another effect owns it and nests its metadata.

    Reference: fiber.ts `effect` `collect` pushes the disposer into the effect's
    own list, deletes it from the fiber list, and appends its `EffectMeta` to the
    parent effect's `children`; `getEffects` therefore returns one root.
    """
    ctx = Context()
    log = []

    def inner_body():
        return lambda: log.append("nested-disposed")

    def outer_body():
        return ctx.fiber.effect(inner_body, "c10-inner")

    outer = ctx.effect(outer_body, "c10-outer")
    effects = ctx.fiber.get_effects()
    assert [effect["label"] for effect in effects] == ["c10-outer"]
    assert effects[0]["children"] == [{"label": "c10-inner", "children": []}]

    await outer
    assert log == ["nested-disposed"]
    assert ctx.fiber.get_effects() == []


@pytest.mark.asyncio
async def test_c11_plain_disposer_from_apply_has_no_effect_metadata():
    """C11: a plain function returned by `apply` is collected without metadata.

    Reference: fiber.ts `_execute` collects function results through the fiber
    `collect`, and `getEffects` filters out disposers that carry no `EffectMeta`.
    """
    ctx = Context()
    log = []

    def body(c):
        return lambda: log.append("disposed")

    fiber = await ctx.plugin(_ApplyPlugin("c11", body))
    assert fiber.get_effects() == []

    await fiber.dispose()
    assert log == ["disposed"]


@pytest.mark.asyncio
async def test_c12_provide_disposer_awaits_dependents_before_dropping_store_entry():
    """C12: `ctx.provide` teardown wakes dependents, awaits their unload, then drops
    its own fiber-store entry ("ensure self access before dependencies cleanup").

    Reference: reflect.ts `provide` disposer: `delete this.store[key]`,
    `this.notify([name])`, `await Promise.allSettled(fibers.map(fiber => fiber.await()))`,
    then `delete this.ctx.fiber.store![name]`.
    """
    ctx = Context()
    order = []

    def provider_body(c):
        return c.provide("c12-svc", {"v": 1})

    def consumer_body(c):
        async def cleanup():
            await asyncio.sleep(0)
            order.append("dependent-unloaded")

        c.effect(lambda: cleanup, "c12-dependent")
        return None

    provider = await ctx.plugin(_ApplyPlugin("c12-provider", provider_body))
    consumer = await ctx.plugin(_ApplyPlugin("c12-consumer", consumer_body, inject=["c12-svc"]))
    assert consumer.state == FiberState.ACTIVE

    disposal = provider.dispose()
    # The provider's own teardown starts at the call; the dependent is still unloading.
    assert order == []

    await disposal
    assert order == ["dependent-unloaded"]
    assert consumer.state == FiberState.PENDING
    assert ctx.get("c12-svc") is None


@pytest.mark.asyncio
async def test_c13_dispose_starts_teardown_synchronously_and_returns_awaitable():
    """C13: disposal is an async function whose body starts at the call site.

    Reference: fiber.ts `dispose` clears the uid, notifies `internal/plugin`
    observers, and drives the unload before its first `await`.
    """
    ctx = Context()
    log = []

    def body(c):
        c.effect(lambda: (lambda: log.append("unloaded")), "c13-effect")
        return None

    fiber = await ctx.plugin(_ApplyPlugin("c13", body))
    pending = fiber.dispose()

    assert fiber.uid is None
    assert log == ["unloaded"]
    assert inspect.isawaitable(pending)

    await pending
    assert fiber.state == FiberState.DISPOSED

@pytest.mark.asyncio
async def test_c14_reentrant_disposal_during_loading_never_runs_the_plugin_body():
    """C14: a load invalidated while LOADING was reported never runs `apply`.

    Reference: fiber.ts `_reload` awaits a microtask and re-checks
    `this._runner.epoch === oldEpoch` before resolving config and executing; a
    disposer invoked by an `internal/status` observer therefore leaves the fiber
    PENDING work unloaded instead of activating it.
    """
    ctx = Context()
    applied = []
    state = {}

    def on_status(fiber, old):
        if fiber.name == "c14" and old == FiberState.PENDING:
            state["disposal"] = fiber.dispose()

    ctx.on("internal/status", on_status)
    fiber = ctx.plugin(_ApplyPlugin("c14", lambda c: applied.append("applied")))

    assert applied == []
    assert fiber.uid is None
    assert fiber.state == FiberState.DISPOSED

    assert state["disposal"] is not None
    await state["disposal"]
    assert fiber.state == FiberState.DISPOSED


@pytest.mark.asyncio
async def test_c15_iterable_result_disposers_are_collected_without_metadata():
    """C15: an iterable returned by `apply` yields bare collected disposers.

    Reference: fiber.ts `_execute` iterates a returned iterable, running each
    produced item through the fiber `collect`; `getEffects` shows no entry for
    plain functions.
    """
    ctx = Context()
    log = []

    def body(c):
        yield lambda: log.append("first")
        yield lambda: log.append("second")

    fiber = await ctx.plugin(_ApplyPlugin("c15", body))
    assert fiber.get_effects() == []

    await fiber.dispose()
    assert log == ["second", "first"]


@pytest.mark.asyncio
async def test_c16_async_effect_setup_failure_propagates_from_the_disposer():
    """C16: the public disposer reports an async setup failure.

    Reference: fiber.ts `effect` `wrapper.then` chains `Promise.resolve(task)`,
    so awaiting the disposer rejects with the setup reason; the call path
    (`disposeAfter`) awaits disposal and rethrows the same reason.
    """
    ctx = Context()

    async def failing_setup():
        await asyncio.sleep(0)
        raise RuntimeError("async setup failed")

    disposer = ctx.effect(failing_setup, "c16-await")
    with pytest.raises(RuntimeError, match="async setup failed"):
        await disposer
    assert ctx.fiber.get_effects() == []

    gate = asyncio.Event()

    async def gated_setup():
        await gate.wait()
        raise RuntimeError("gated setup failed")

    gated = ctx.effect(gated_setup, "c16-call")
    gate.set()
    with pytest.raises(RuntimeError, match="gated setup failed"):
        await gated()
    assert ctx.fiber.get_effects() == []


class _C17Config:
    """Config schema recording the exact merge inputs of `resolveConfig`."""

    def __init__(self):
        self.calls = []

    def merge(self, *configs):
        self.calls.append(configs)
        merged = {}
        for config in configs:
            merged.update(config)
        return merged


def test_c17_intercept_config_merges_once_per_ancestor_level():
    """C17: every intercept level contributes one merge input, root first.

    Reference: context.ts `extend` creates a child whose intercept map inherits
    the parent's through the prototype chain, and service.ts `resolveConfig`
    collects one own entry per level (`Object.hasOwn`).
    """
    recorder = _C17Config()

    class InterceptedService(Service):
        name = "c17-svc"
        Config = recorder

    root = Context()
    leaf = root.intercept("c17-svc", {"root": 1}).intercept("c17-svc", {"mid": 2})
    child = leaf.extend()

    # `extend` gives the child no intercept entry of its own; its ancestors are
    # reached through the context chain.
    assert child._intercept_map == {}
    assert InterceptedService(child).resolve_intercept_config() == {"root": 1, "mid": 2}
    assert recorder.calls == [
        ({"root": 1}, {"mid": 2}),
    ]

    recorder.calls.clear()
    single = Context().intercept("c17-svc", {"only": True}).extend()
    assert InterceptedService(single).resolve_intercept_config() == {"only": True}
    assert recorder.calls == [
        ({"only": True},),
    ]


@pytest.mark.asyncio
async def test_c18_parallel_resolves_without_results():
    """C18: `parallel` waits for every listener and resolves with no value.

    Reference: events.ts `parallel` awaits `Promise.allSettled` and returns
    `undefined`; only failures surface, as an `AggregateError`.
    """
    ctx = Context()
    ctx.on("c18-evt", lambda: "ignored")

    assert await ctx.parallel("c18-evt") is None

    def failing_listener():
        raise ValueError("listener failed")

    ctx.on("c18-fail", failing_listener)
    with pytest.raises(AggregateError) as excinfo:
        await ctx.parallel("c18-fail")
    assert len(excinfo.value.errors) == 1


@pytest.mark.asyncio
async def test_c19_bail_dispatches_synchronously():
    """C19: `bail` runs listeners synchronously until one returns a bail value.

    Reference: events.ts `bail` calls each listener and stops at the first value
    that is not `null`, `false`, or `undefined`; it never awaits.
    """
    ctx = Context()
    called = []

    ctx.on("c19-evt", lambda: called.append(1) or None)
    ctx.on("c19-evt", lambda: called.append(2) or "stop")
    ctx.on("c19-evt", lambda: called.append(3) or "unreachable")

    result = ctx.bail("c19-evt")
    assert result == "stop"
    assert called == [1, 2]
    assert not inspect.isawaitable(result)

    ctx.on("c19-false", lambda: False)
    ctx.on("c19-false", lambda: "value")
    assert ctx.bail("c19-false") == "value"

    async def async_listener():
        return "async"

    ctx.on("c19-async", async_listener)
    # A coroutine result is a bail value, exactly like the promise an async
    # listener returns in the reference (which `isBailed` also accepts).
    pending = ctx.bail("c19-async")
    assert inspect.isawaitable(pending)
    pending.close()


@pytest.mark.asyncio
async def test_c20_async_iterable_result_disposers_are_collected_on_the_fiber():
    """C20: an async-iterable `apply` result is drained onto the fiber.

    Reference: fiber.ts `_execute` asyncIterator branch consumes the iterator
    through the fiber `collect` while the load is in flight, so the yielded
    disposers carry no effect metadata and unload in reverse order.
    """
    ctx = Context()
    log = []

    async def body(c):
        yield lambda: log.append("first")
        await asyncio.sleep(0)
        yield lambda: log.append("second")

    fiber = ctx.plugin(_ApplyPlugin("c20", body))
    await fiber.await_settled()

    assert fiber.state == FiberState.ACTIVE
    assert fiber.get_effects() == []

    await fiber.dispose()
    assert log == ["second", "first"]


@pytest.mark.asyncio
async def test_c21_context_get_second_positional_parameter_is_strict():
    """C21: `ctx.get(name, strict)` follows the reference parameter order.

    Reference: reflect.ts `get(name, strict = true)` resolves only ACTIVE
    providers when `strict` is true, and `false` reads the store directly.
    """
    ctx = Context()

    async def body(c):
        c.provide("c21-svc", "value")
        await asyncio.sleep(0.03)

    fiber = ctx.plugin(_ApplyPlugin("c21", body))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert fiber.state == FiberState.LOADING

    assert ctx.get("c21-svc", True) is None
    assert ctx.get("c21-svc", False) == "value"

    await fiber.await_settled()
    assert ctx.get("c21-svc", True) == "value"
