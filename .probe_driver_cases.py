"""Probe: loop-less listener shapes that must survive hand-driven settlement."""
import asyncio
import sys
import threading

from dsh.cordis.events import EventBus

results = []


def check(label, got, expected):
    ok = got == expected
    results.append((label, ok, got, expected))
    print(("PASS " if ok else "FAIL "), label, "->", got, "" if ok else ("expected %r" % (expected,)))
    sys.stdout.flush()


# 1. sequential awaited delays, value threading
bus = EventBus()
steps = []


async def sequential2():
    steps.append("start")
    await asyncio.sleep(0.01)
    steps.append(await asyncio.sleep(0.01, "value"))
    steps.append("end")


bus.on("probe.cases", sequential2)
bus.emit("probe.cases")
check("sequential delays at emit return", list(steps), ["start"])
check("sequential delays joined", bus.join_loopless_settlements(5.0), True)
check("sequential delays steps", list(steps), ["start", "value", "end"])

# 2. awaited failure is reported, later listener still runs
errors = []


class RecordingLogger:
    def error(self, format_str, *args):
        errors.append(format_str % args)


class LoggingContext:
    def logger(self, name):
        return RecordingLogger()


bus = EventBus(ctx=LoggingContext())
steps = []


async def failing():
    steps.append("failing-prefix")
    await asyncio.sleep(0.01)
    raise RuntimeError("boom")


def later():
    steps.append("later")


bus.on("probe.cases.fail", failing)
bus.on("probe.cases.fail", later)
bus.emit("probe.cases.fail")
check("failing listener ordering at return", list(steps), ["failing-prefix", "later"])
check("failing listener joined", bus.join_loopless_settlements(5.0), True)
check("failing listener reported", errors, ["Listener for 'probe.cases.fail' failed: boom"])

# 3. try/finally cleanup runs when the settlement is cancelled. Cancelling the settlement marks
#    its future done before the owned loop has delivered the cancellation, so the cleanup itself
#    is what is awaited here.
bus = EventBus()
cleaned = []
cleanup_ran = threading.Event()


async def cancellable():
    cleaned.append("prefix")
    try:
        await asyncio.sleep(30.0)
        cleaned.append("never")
    finally:
        cleaned.append("finally")
        cleanup_ran.set()


bus.on("probe.cases.cancel", cancellable)
bus.emit("probe.cases.cancel")
settlements = list(bus._loopless_settlements)
check("cancellable pending", bus.pending_loopless_settlements(), 1)
for settlement in settlements:
    settlement.cancel()
check("cancellable cleanup ran", cleanup_ran.wait(10.0), True)
check("cancellable joined after cancel", bus.join_loopless_settlements(5.0), True)
check("cancellable cleanup steps", list(cleaned), ["prefix", "finally"])

# 4. listener that never suspends, and a listener that only awaits coroutines
bus = EventBus()
steps = []


async def immediate():
    steps.append("immediate")


async def no_suspend_call():
    async def inner():
        steps.append("inner")
    await inner()
    steps.append("after-inner")


bus.on("probe.cases.immediate", immediate)
bus.on("probe.cases.immediate", no_suspend_call)
bus.emit("probe.cases.immediate")
check("immediate listeners at return", list(steps), ["immediate", "inner", "after-inner"])
check("immediate listeners pending", bus.pending_loopless_settlements(), 0)

# 5. gather / wait_for / ensure_future awaits inside a loop-less listener
bus = EventBus()
steps = []


async def gatherer():
    steps.append("gather-prefix")
    values = await asyncio.gather(asyncio.sleep(0.01, 1), asyncio.sleep(0.01, 2))
    steps.append(tuple(values))
    steps.append(await asyncio.wait_for(asyncio.sleep(0.01, "timed"), timeout=1.0))
    steps.append(await asyncio.ensure_future(asyncio.sleep(0.01, "tasked")))


bus.on("probe.cases.gather", gatherer)
bus.emit("probe.cases.gather")
check("gather at return", list(steps), ["gather-prefix"])
check("gather joined", bus.join_loopless_settlements(5.0), True)
check("gather steps", list(steps), ["gather-prefix", (1, 2), "timed", "tasked"])

# 6. listener awaiting a pending future resolved from the test thread
bus = EventBus()
steps = []
futures = []


async def future_waiter():
    steps.append("future-prefix")
    fut = asyncio.Future()
    futures.append(fut)
    steps.append(await fut)


bus.on("probe.cases.future", future_waiter)
bus.emit("probe.cases.future")
check("future waiter pending", bus.pending_loopless_settlements(), 1)
futures[0].get_loop().call_soon_threadsafe(futures[0].set_result, "resolved")
check("future waiter joined", bus.join_loopless_settlements(5.0), True)
check("future waiter steps", list(steps), ["future-prefix", "resolved"])

failed = [r for r in results if not r[1]]
print("cases:", len(results), "failures:", len(failed))
