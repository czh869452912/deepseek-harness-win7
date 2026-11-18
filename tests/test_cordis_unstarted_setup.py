"""CLI loop shutdown must close setup coroutines whose wrappers never started."""
import asyncio
import inspect

import pytest

from dsh.cordis.context import Context


@pytest.mark.parametrize('kind', ['apply', 'init'])
def test_loop_shutdown_closes_unstarted_plugin_setup(kind):
    observed = []
    entered = []

    async def setup():
        entered.append(True)

    def create_setup(*args):
        coroutine = setup()
        observed.append(coroutine)
        return coroutine

    class Initializing:
        init = staticmethod(create_setup)

    async def run():
        ctx = Context()
        fiber = ctx.plugin({'apply': create_setup} if kind == 'apply' else Initializing)
        # The reload creates its async wrapper in this checkpoint. Cancel it
        # before its first step; loop shutdown must close the owned coroutine.
        await asyncio.sleep(0)
        fiber.inertia.cancel()

    asyncio.run(run())
    assert len(observed) == 1
    assert not entered
    assert inspect.getcoroutinestate(observed[0]) == inspect.CORO_CLOSED
