"""Reconstruct the reviewed (pre-barrier) events.py body for the strictness probe.

The reviewed working-tree body is rebuilt by reverting exactly the three regions this
repair replaced: the loop-less settlement helpers, the emit dispatch loop and the
loop-less settlement entry point.
"""

import os

CURRENT = "dsh/cordis/events.py"
OUT = ".probe_backup/events_reviewed.py"

with open(CURRENT, "r", encoding="utf-8", newline="") as fh:
    text = fh.read()

def crlf(block):
    return block.replace("\n", "\r\n")

REVIEWED_SETTLEMENT = crlf('''async def _enter_then_settle(result: Any, event_name: str, ctx: Any, entered: threading.Event) -> None:
    """
    Start one loop-less listener, release its dispatcher, then settle and report it.

    `ensure_future` queues the listener's first step before the `sleep(0)`
    continuation is queued, so the listener body has run everything up to its
    first real suspension once `entered` is set: the part of the body that
    upstream runs before `emit` returns. `entered` is set on every path. A
    listener failure is reported before this settlement completes, so a caller
    that joins it observes the report.
    """
    try:
        listener = asyncio.ensure_future(result)
        await asyncio.sleep(0)
    finally:
        entered.set()
    try:
        await listener
    except Exception as exc:
        # The failure stays with the settlement, as the in-loop branch leaves it
        # with the scheduled task; reporting it here is the only handling it gets.
        _report_loopless_listener_failure(asyncio.get_running_loop(), event_name, ctx, exc)''')

REVIEWED_EMIT = crlf('''    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """
        Dispatch an event synchronously, ignoring return values matching TS EventBus.emit.

        A listener that returns an awaitable is scheduled on the running loop, or owned by
        `_settle_loopless_listener` when the dispatching caller holds no loop; `emit` returns
        without waiting for that settlement either way (events.ts:194-196).
        """
        event_name, actual_args, caller_ctx = _normalize_event_call(event_name, args, self.ctx, kwargs)
        listeners = self._dispatch_hooks("emit", event_name, actual_args, caller_ctx)
        for listener in listeners:
            sig = None
            try:
                sig = inspect.signature(listener)
            except Exception:
                pass

            res = listener(*actual_args, **kwargs)
            if inspect.isawaitable(res):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(res)
                except RuntimeError:
                    self._settle_loopless_listener(res, event_name, caller_ctx or self.ctx)

    def _settle_loopless_listener(self, result: Any, event_name: str, ctx: Any) -> None:
        """
        Hand a listener's returned awaitable to the owned loop and return once its body starts.

        Upstream `emit` returns without waiting for a listener's returned promise, so the
        settlement is owned instead of awaited: it stays registered until it finishes,
        `join_loopless_settlements` can wait for it, and the awaitable is never collected
        unawaited. The listener's synchronous prefix still runs on the owned loop thread
        before this returns, matching the reference, so that prefix must not block on the
        dispatching thread.
        """
        loop = _loopless_owner()
        entered = threading.Event()
        settlement = asyncio.run_coroutine_threadsafe(_enter_then_settle(result, event_name, ctx, entered), loop)
        self._loopless_settlements.add(settlement)
        settlement.add_done_callback(lambda done: self._retire_loopless_settlement(done, loop, event_name, ctx))
        entered.wait()

''')

# Region A: loop-less settlement helpers -> reviewed single-listener settlement.
start = text.index("class _LooplessDispatchBarrier:")
end = text.index("def _release_loopless_barrier(")
text = text[:start] + REVIEWED_SETTLEMENT + "\r\n\r\n\r\n" + text[end:]
# Region B: drop the deferred barrier release helper.
start = text.index("def _release_loopless_barrier(")
end = text.index("def _normalize_event_call(")
text = text[:start] + text[end:]
# Region C: emit dispatch loop and loop-less settlement entry point.
start = text.index("    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:")
end = text.index("    def _retire_loopless_settlement(")
text = text[:start] + REVIEWED_EMIT + text[end:]

assert "_LooplessDispatchBarrier" not in text
assert "_drive_loopless_settlement" not in text

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="") as fh:
    fh.write(text)

print("reconstructed reviewed body")
