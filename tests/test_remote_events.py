import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.typert.registry import TypertRegistry
from dsh.typert.remote_events import RemoteEvents, parse_result


class Scope(Plugin):
    def apply(self, ctx):
        self.context = ctx


async def setup():
    ctx = Context()
    await ctx.plugin(TypertRegistry)
    scope = await ctx.plugin(Scope)
    child = scope.plugin.context
    ctx.get("typert").contexts.registerHost("agent", SimpleNamespace(wire="agentId", wireTypeSymbol="AgentId", identity=lambda value: "a" if value is child else None, resolve=lambda _: child))
    events, queue = RemoteEvents(ctx), asyncio.Queue()
    async def source(signal):
        while True:
            yield await queue.get()
    dispose = events.register(source, {"home": "C:/Users/test"})
    return ctx, scope, child, events, queue, dispose


@pytest.mark.asyncio
async def test_multiclient_waterfall_results_cancel_other_deliveries_and_ignore_stale_replies():
    ctx, scope, child, events, queue, dispose = await setup()
    streams = [events.open({"args": {}}, AbortController().signal) for _ in range(2)]
    try:
        ready = [await stream.__anext__() for stream in streams]
        subject = object()
        result = asyncio.get_running_loop().create_future()
        await queue.put({"event": "agent/pre-step", "request": {"agent": subject, "value": "input"},
                         "context": {"value": child, "subject": subject}, "resolve": result.set_result, "reject": result.set_exception})
        frames = [await stream.__anext__() for stream in streams]
        assert frames[0] == frames[1]
        assert frames[0]["request"] == {"value": "input"}
        reply = {"args": {"clientId": ready[0]["clientId"], "eventId": frames[0]["eventId"], "outcome": {"kind": "result", "value": "output"}}}
        events.result(reply)
        assert await result == {"kind": "result", "value": "output"}
        assert (await streams[1].__anext__())["type"] == "cancel"
        events.result(reply)
        assert not events.pending
    finally:
        for stream in streams:
            await stream.aclose()
        await dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_disconnect_retains_pending_and_new_generation_receives_it_until_context_disposal():
    ctx, scope, child, events, queue, dispose = await setup()
    stream = events.open({"args": {}}, AbortController().signal)
    replacement = None
    try:
        old = await stream.__anext__()
        subject, result = object(), asyncio.get_running_loop().create_future()
        await queue.put({"event": "agent/pre-step", "request": {"agent": subject},
                         "context": {"value": child, "subject": subject}, "resolve": result.set_result, "reject": result.set_exception})
        frame = await stream.__anext__()
        await stream.aclose()
        assert not result.done() and events.pending
        replacement = events.open({"args": {}}, AbortController().signal)
        fresh = await replacement.__anext__()
        assert fresh["clientId"] != old["clientId"]
        assert await replacement.__anext__() == frame
        await scope.dispose()
        with pytest.raises(RuntimeError, match="Context was released"):
            await result
        assert (await replacement.__anext__())["type"] == "cancel"
    finally:
        await stream.aclose()
        if replacement is not None:
            await replacement.aclose()
        await dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_all_clients_delegate_and_registration_disposal_ends_stream():
    ctx, scope, child, events, queue, dispose = await setup()
    stream = events.open({"args": {}}, AbortController().signal)
    try:
        ready = await stream.__anext__()
        await queue.put({"event": "session/event", "args": ["s", {"seq": 1}]})
        assert (await stream.__anext__())["type"] == "emit"
        result, subject = asyncio.get_running_loop().create_future(), object()
        await queue.put({"event": "agent/pre-step", "request": {"agent": subject}, "context": {"value": child, "subject": subject}, "resolve": result.set_result, "reject": result.set_exception})
        frame = await stream.__anext__()
        events.result({"args": {"clientId": ready["clientId"], "eventId": frame["eventId"], "outcome": {"kind": "next"}}})
        assert await result == {"kind": "next"}
        await dispose()
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()
    finally:
        await stream.aclose()
        await dispose()
        await ctx.fiber.dispose()


@pytest.mark.parametrize("value", [float("nan"), -0.0, {"x": object()}])
def test_remote_event_results_reject_lossy_values(value):
    with pytest.raises(ValueError):
        parse_result({"clientId": "c", "eventId": "e", "outcome": {"kind": "result", "value": value}})
