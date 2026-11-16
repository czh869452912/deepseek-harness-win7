"""A caller deadline never cancels the generation's actual operation."""
import asyncio

from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import js_to_string
from dsh.mcp.diagnostic_current import McpLocalError


async def with_deadline(operation, remaining_ms, timeout_message):
    task = asyncio.ensure_future(operation)
    def settled(completed):
        if not completed.cancelled():
            completed.exception()
    task.add_done_callback(settled)
    try:
        done, _ = await asyncio.wait([task],timeout=max(1,remaining_ms)/1000)
        if not done:
            raise McpLocalError(timeout_message)
        return task.result()
    except ThrownValueError as error:
        raise McpLocalError(js_to_string(error.value)) from None
