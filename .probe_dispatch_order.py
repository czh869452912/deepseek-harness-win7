"""Probe: loop-less emit must invoke every listener before any continuation resumes."""
import asyncio

from dsh.cordis.events import EventBus


def run_once():
    bus = EventBus()
    steps = []
    seen = []

    async def first():
        steps.append("first-prefix")
        await asyncio.sleep(0)
        seen.append(list(steps))
        steps.append("first-continuation")

    def second():
        steps.append("second-listener")

    async def third():
        steps.append("third-prefix")
        await asyncio.sleep(0)
        steps.append("third-continuation")

    bus.on("probe.order", first)
    bus.on("probe.order", second)
    bus.on("probe.order", third)
    bus.emit("probe.order")
    at_return = list(steps)
    pending = bus.pending_loopless_settlements()
    joined = bus.join_loopless_settlements(10.0)
    return at_return, pending, joined, list(steps), seen


EXPECTED_AT_RETURN = ["first-prefix", "second-listener", "third-prefix"]
EXPECTED_FINAL = [
    "first-prefix",
    "second-listener",
    "third-prefix",
    "first-continuation",
    "third-continuation",
]
EXPECTED_SEEN = [["first-prefix", "second-listener", "third-prefix"]]

bad_return = 0
bad_pending = 0
bad_final = 0
bad_seen = 0
example = None
for _ in range(200):
    at_return, pending, joined, final, seen = run_once()
    if at_return != EXPECTED_AT_RETURN:
        bad_return += 1
        example = ("return", at_return)
    if pending != 2 or not joined:
        bad_pending += 1
        example = example or ("pending", pending, joined)
    if final != EXPECTED_FINAL:
        bad_final += 1
        example = example or ("final", final)
    if seen != EXPECTED_SEEN:
        bad_seen += 1
        example = example or ("seen", seen)

print("runs: 200")
print("bad_at_return:", bad_return)
print("bad_pending:", bad_pending)
print("bad_final:", bad_final)
print("bad_seen_by_continuation:", bad_seen)
print("example:", example)
