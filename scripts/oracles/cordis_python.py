"""Observe the same C1-C21 scenarios as cordis.mts without asserting parity."""
import asyncio
import copy
import inspect
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.timer import TimerService


class Body(Plugin):
    def __init__(self, name, body, inject=()):
        self.name = name
        self.body = body
        self.inject = list(inject)

    def apply(self, ctx, config=None):
        return self.body(ctx, config)


async def settled(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def scenario(number):
    if number >= 37:
        from cordis_include import scenario as include_scenario
        return await include_scenario(number)
    if number >= 31:
        from cordis_consumers import scenario as consumer_scenario
        return await consumer_scenario(number)
    ctx = Context()
    log = []

    async def loaded(name, body, inject=()):
        fiber = ctx.plugin(Body(name, body, inject))
        await fiber.await_settled()
        return fiber

    if number == 1:
        fiber = await loaded("provider", lambda c, cfg: c.provide("svc", {"v": 1}))
        before = [fiber.state, ctx.get("svc")]
        await fiber.dispose()
        return {"before": before, "after": [fiber.state, ctx.get("svc")]}
    if number == 2:
        async def body(c, cfg):
            await asyncio.sleep(0)
            log.append("setup")
            return lambda: log.append("dispose")
        fiber = await loaded("async-effect", body)
        before = log[:]
        await fiber.dispose()
        return {"before": before, "after": log}
    if number in (3, 21):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def body(c, cfg):
            c.provide("svc", "value")
            entered.set()
            await finish.wait()
        fiber = ctx.plugin(Body("loading", body))
        await entered.wait()
        pending = [fiber.state, ctx.get("svc"), ctx.get("svc", False), ctx.svc]
        finish.set()
        await fiber.await_settled()
        active = [fiber.state, ctx.get("svc")]
        await fiber.dispose()
        return {"pending": pending, "active": active}
    if number in (4, 5):
        events = []
        ctx.on("internal/status", lambda f, old: events.append([f.name, old, f.state]))
        def body(c, cfg):
            log.append("apply")
            return lambda: log.append("dispose")
        consumer = ctx.plugin(Body("consumer", body, ["svc"]))
        pending = consumer.state
        provider = await loaded("provider", lambda c, cfg: c.provide("svc", 1))
        await consumer.await_settled()
        active = consumer.state
        await provider.dispose()
        await consumer.await_settled()
        return {"pending": pending, "active": active, "final": consumer.state, "log": log, "events": events}
    if number == 6:
        def observe(f):
            if f.name == "pending" and f.uid is not None:
                f.ctx.effect(lambda: lambda: log.append("drained"), "observer")
        ctx.on("internal/plugin", observe)
        fiber = ctx.plugin(Body("pending", lambda c, cfg: log.append("unexpected"), ["missing"]))
        before = fiber.state
        await fiber.dispose()
        return {"before": before, "final": fiber.state, "log": log}
    if number == 7:
        def body(c, config):
            log.append(["apply", config])
            def hook(cfg, no_save, next_fn):
                log.append(["hook", cfg, no_save])
                return next_fn()
            c.on("internal/update", hook)
            return lambda: log.append(["dispose"])
        fiber = await loaded("updatable", body)
        await settled(fiber.update({"n": 2}))
        await fiber.await_settled()
        fiber.ctx.on("internal/update", lambda *args: log.append(["veto"]))
        await settled(fiber.update({"n": 3}))
        await fiber.await_settled()
        return {"log": log, "config": fiber.config, "state": fiber.state}
    if number == 8:
        def on_get(c, name, error, next_fn):
            log.append(name)
            return "intercepted" if name == "virtual" else next_fn()
        ctx.on("internal/get", on_get)
        ctx.provide("declared", "value")
        root = ctx.get("declared")
        seen = {}
        def body(c, cfg):
            seen.update(attribute=c.declared, virtual=c.virtual, get=c.get("declared"))
        await loaded("reader", body, ["declared"])
        return {"root": root, "seen": seen, "log": log}
    if number == 9:
        dispose = ctx.on("event", lambda: None)
        before = ctx.fiber.get_effects()
        first, second = dispose(), dispose()
        after = ctx.fiber.get_effects()
        ctx.effect(lambda: None)
        return {"before": before, "first": first, "second": second, "after": after, "anonymous": ctx.fiber.get_effects()}
    if number == 10:
        outer = ctx.effect(lambda: ctx.effect(lambda: lambda: log.append("nested-disposed"), "inner"), "outer")
        before = copy.deepcopy(ctx.fiber.get_effects())
        dispose = await outer
        await settled(dispose())
        return {"before": before, "after": ctx.fiber.get_effects(), "log": log}
    if number in (11, 15, 20):
        body = lambda c, cfg: lambda: log.append("disposed")
        if number == 15:
            def body(c, cfg):
                yield lambda: log.append("first")
                yield lambda: log.append("second")
        if number == 20:
            async def body(c, cfg):
                yield lambda: log.append("first")
                await asyncio.sleep(0)
                yield lambda: log.append("second")
        fiber = await loaded("effects", body)
        before = [fiber.state, fiber.get_effects()]
        await fiber.dispose()
        return {"before": before, "log": log, "final": fiber.state}
    if number == 12:
        entered, finish = asyncio.Event(), asyncio.Event()
        provider = await loaded("provider", lambda c, cfg: c.provide("svc", 1))
        def body(c, cfg):
            async def cleanup():
                log.append("cleanup-enter")
                entered.set()
                await finish.wait()
                log.append("cleanup-exit")
            c.effect(lambda: cleanup, "cleanup")
        consumer = await loaded("consumer", body, ["svc"])
        disposal = provider.dispose()
        immediate = log[:]
        await entered.wait()
        pending = {"log": log[:], "visible": ctx.get("svc"), "ownerRetains": bool((provider.store or {}).get("svc"))}
        finish.set()
        await disposal
        return {"immediate": immediate, "pending": pending, "log": log, "final": consumer.state, "ownerRetains": bool((provider.store or {}).get("svc"))}
    if number == 13:
        def body(c, cfg):
            c.effect(lambda: lambda: log.append("unloaded"), "cleanup")
        fiber = await loaded("dispose", body)
        pending = fiber.dispose()
        immediate = {"uidCleared": fiber.uid is None, "log": log[:], "awaitable": inspect.isawaitable(pending)}
        await pending
        return {"immediate": immediate, "final": fiber.state, "log": log}
    if number == 14:
        state = {}
        def observe(f, old):
            if f.name == "reentrant" and old == 0:
                state["disposal"] = f.dispose()
        ctx.on("internal/status", observe)
        fiber = ctx.plugin(Body("reentrant", lambda c, cfg: log.append("applied")))
        immediate = {"log": log[:], "uidCleared": fiber.uid is None, "state": fiber.state}
        await settled(state.get("disposal"))
        await fiber.await_settled()
        return {"immediate": immediate, "log": log, "final": fiber.state}
    if number == 16:
        async def setup():
            await asyncio.sleep(0)
            raise RuntimeError("setup failed")
        dispose = ctx.effect(setup, "failed")
        awaited = called = ""
        try:
            await dispose
        except RuntimeError as exc:
            awaited = str(exc)
        finish = asyncio.Event()
        async def gated():
            await finish.wait()
            raise RuntimeError("gated failed")
        pending = ctx.effect(gated, "gated")
        finish.set()
        try:
            await pending()
        except RuntimeError as exc:
            called = str(exc)
        return {"awaited": awaited, "called": called, "effects": ctx.fiber.get_effects()}
    if number == 17:
        class Config:
            def merge(self, *configs):
                log.append(list(configs))
                result = {}
                for config in configs:
                    result.update(config)
                return result
        class Intercepted(Service):
            name = "svc"
        Intercepted.Config = Config()
        leaf = ctx.intercept("svc", {"root": 1}).intercept("svc", {"mid": 2}).extend()
        return {"merged": Intercepted(leaf).resolve_intercept_config(), "inputs": log}
    if number == 18:
        ctx.on("ok", lambda: "ignored")
        result = await ctx.parallel("ok")
        def fail():
            raise RuntimeError("listener failed")
        ctx.on("fail", fail)
        errors = []
        try:
            await ctx.parallel("fail")
        except Exception as exc:
            errors = [str(error) for error in exc.errors]
        return {"result": result, "errors": errors}
    if number == 19:
        ctx.on("event", lambda: log.append(1))
        ctx.on("event", lambda: log.append(2) or "stop")
        ctx.on("event", lambda: log.append(3) or "unreachable")
        result = ctx.bail("event")
        ctx.on("false", lambda: False)
        ctx.on("false", lambda: "value")
        async def listener():
            return "async"
        ctx.on("async", listener)
        pending = ctx.bail("async")
        return {"result": result, "log": log, "afterFalse": ctx.bail("false"), "awaitable": inspect.isawaitable(pending), "resolved": await pending}
    if number == 22:
        finish, done_a, done_b = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def first():
            log.append("a-prefix")
            await finish.wait()
            log.append("a-tail")
            done_a.set()
        async def second():
            log.append("b-prefix")
            await finish.wait()
            log.append("b-tail")
            done_b.set()
        ctx.on("event", first)
        ctx.on("event", lambda: log.append("sync"))
        ctx.on("event", second)
        ctx.emit("event")
        immediate = log[:]
        finish.set()
        await asyncio.gather(done_a.wait(), done_b.wait())
        return {"immediate": immediate, "log": log}
    if number == 23:
        def first():
            log.append("first")
            raise RuntimeError("sync failure")
        ctx.on("event", first)
        ctx.on("event", lambda: log.append("unreachable"))
        error = ""
        try:
            ctx.emit("event")
        except RuntimeError as exc:
            error = str(exc)
        return {"error": error, "log": log}
    if number == 24:
        reported = asyncio.Event()
        errors = []
        def exception_handler(loop, context):
            errors.append(str(context["exception"]))
            reported.set()
        asyncio.get_running_loop().set_exception_handler(exception_handler)
        async def first():
            log.append("prefix")
            raise RuntimeError("async failure")
        ctx.on("event", first)
        ctx.on("event", lambda: log.append("peer"))
        ctx.emit("event")
        immediate = log[:]
        await reported.wait()
        return {"immediate": immediate, "log": log, "errors": errors}
    if number in (25, 27, 30):
        entered, finish = asyncio.Event(), asyncio.Event()
        state = {}
        def body(c, cfg):
            async def cleanup():
                log.append("cleanup-enter")
                entered.set()
                await finish.wait()
                log.append("cleanup-exit")
            state["release"] = c.effect(lambda: cleanup, "resource")
        fiber = await loaded("owner", body)
        first = asyncio.ensure_future(settled(fiber.dispose() if number == 30 else state["release"]()))
        await entered.wait()
        cancellation = None
        if number == 30:
            first.cancel()
            try:
                await first
            except asyncio.CancelledError:
                cancellation = "observer cancelled"
        repeated = asyncio.ensure_future(settled(fiber.dispose() if number == 30 else state["release"]()))
        state["owner_done"] = False
        disposal = ctx.fiber.dispose() if number in (27, 30) else fiber.dispose()
        async def join_owner():
            await disposal
            state["owner_done"] = True
        owner = asyncio.create_task(join_owner())
        pending = {"log": log[:], "ownerDone": state["owner_done"]}
        finish.set()
        await asyncio.gather(first, repeated, owner, return_exceptions=True)
        return {"pending": pending, "log": log, "ownerDone": state["owner_done"], "cancellation": cancellation}
    if number == 26:
        entered, finish = asyncio.Event(), asyncio.Event()
        async def body(c, cfg):
            yield lambda: log.append("first-disposed")
            entered.set()
            await finish.wait()
            yield lambda: log.append("late-disposed")
            log.append("unreachable-next")
        fiber = ctx.plugin(Body("iterator", body))
        await entered.wait()
        disposal = fiber.dispose()
        immediate = log[:]
        finish.set()
        await disposal
        return {"immediate": immediate, "log": log, "final": fiber.state}
    if number in (28, 29):
        await ctx.plugin(TimerService)
        state = {}
        def body(c, cfg):
            if number == 28:
                state["operation"] = c.timeout(60000)
            else:
                state["operation"] = c.interval(60000).__anext__()
        fiber = await loaded("timer-owner", body, ["timer"])
        async def observe():
            try:
                await state["operation"]
                return "unexpected-resolution"
            except Exception as exc:
                return str(exc)
        result = asyncio.create_task(observe())
        await fiber.dispose()
        return {"result": await result, "effects": fiber.get_effects(), "final": fiber.state}
    raise ValueError("Unknown scenario: " + str(number))


if __name__ == "__main__":
    case = int(sys.argv[1])
    observation = asyncio.run(scenario(case))
    print(json.dumps({"case": "C%d" % case, "observation": observation}, ensure_ascii=False))
