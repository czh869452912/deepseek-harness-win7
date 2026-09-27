"""Python 3.8 adaptations for framework-owned Promise continuation boundaries."""
import asyncio
import contextvars
import inspect
from typing import Any, Optional


async def resume_coroutine(listener: Any, awaited: Any) -> Any:
    """Continue a coroutine already entered by emit, preserving its suspension."""
    while True:
        failure: Optional[BaseException] = None
        value = None
        try:
            if awaited is None:
                await asyncio.sleep(0)
            else:
                if isinstance(awaited, asyncio.Future):
                    awaited._asyncio_future_blocking = False
                value = await awaited
        except BaseException as exc:
            failure = exc
        try:
            awaited = listener.throw(failure) if failure is not None else listener.send(value)
        except StopIteration as stop:
            return stop.value


async def await_callback_result(result: Any) -> Any:
    """Mirror a framework-owned JS await boundary, including already settled results."""
    if inspect.iscoroutine(result):
        context = contextvars.copy_context()
        try:
            awaited = context.run(result.send, None)
        except StopIteration as stop:
            value = stop.value
        except BaseException:
            # An async throw rejects a Promise; it does not bypass its await tail.
            await asyncio.sleep(0)
            raise
        else:
            task = context.run(asyncio.create_task, resume_coroutine(result, awaited))
            try:
                return await task
            finally:
                if task.cancelled():
                    result.close()
        await asyncio.sleep(0)
        return value
    if not inspect.isawaitable(result):
        await asyncio.sleep(0)
        return result
    if isinstance(result, asyncio.Future) and result.done():
        await asyncio.sleep(0)
    if not isinstance(result, asyncio.Future):
        async def assimilate():
            return await result
        return await await_callback_result(assimilate())
    return await result


