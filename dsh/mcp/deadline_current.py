"""A caller deadline never cancels the generation's actual operation."""
import asyncio
import time

from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import js_to_string
from dsh.mcp.diagnostic_current import McpLocalError


async def with_deadline(operation, remaining_ms, timeout_message):
    task = asyncio.ensure_future(operation)
    loop = asyncio.get_running_loop()
    result = loop.create_future()
    expires = time.perf_counter() + max(1,remaining_ms)/1000
    timer = [None]

    def timeout():
        remaining = expires-time.perf_counter()
        if remaining > 0:
            # Windows 7's asyncio clock can fire short timers before their
            # budget. Check the high-resolution clock before rejecting work.
            timer[0] = loop.call_later(remaining,timeout)
        elif not result.done():
            result.set_exception(McpLocalError(timeout_message))

    def settled(completed):
        if timer[0] is not None:
            timer[0].cancel()
        if completed.cancelled():
            if not result.done():
                result.cancel()
            return
        error = completed.exception()
        if result.done():
            return
        if isinstance(error,ThrownValueError):
            error = McpLocalError(js_to_string(error.value))
        if error is not None:
            result.set_exception(error)
        else:
            result.set_result(completed.result())

    timer[0] = loop.call_later(max(0,expires-time.perf_counter()),timeout)
    task.add_done_callback(settled)
    def observed(completed):
        if not completed.cancelled():
            completed.exception()
    result.add_done_callback(observed)
    return await asyncio.shield(result)
