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
"""

import asyncio
import inspect

import pytest

from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.cordis.plugin import Plugin


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
