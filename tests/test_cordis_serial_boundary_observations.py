"""Frozen upstream observations for serial's settled-result await boundary."""
import asyncio
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('serial_boundary_adapter',ROOT/'scripts/oracles/cordis_serial_boundaries.py')
ADAPTER=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(ADAPTER)
REPORT=json.loads((ROOT/'migration/evidence/artifacts/CORDIS-AWAIT-AFTER-20260927.json').read_text(encoding='utf-8'))
@pytest.mark.parametrize('case',[63,64,65,66,67])
def test_serial_await_boundary_matches_upstream(case):
    expected=next(row['upstream']['observation'] for row in REPORT['cases'] if row['case']=='C%d'%case)
    assert asyncio.run(ADAPTER.scenario(case))==expected

@pytest.mark.asyncio
async def test_custom_awaitable_retains_serial_checkpoint():
    from dsh.cordis.context import Context
    ctx, log = Context(), []
    class Settled:
        def __await__(self):
            if False:
                yield
            return None
    def first():
        asyncio.get_running_loop().call_soon(log.append, 'checkpoint')
        return Settled()
    ctx.on('event', first)
    ctx.on('event', lambda: log.append('second'))
    try:
        await ctx.serial('event')
        assert log == ['checkpoint', 'second']
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_serial_closes_pending_listener():
    from dsh.cordis.context import Context
    ctx, entered, stopped = Context(), asyncio.Event(), asyncio.Event()
    async def first():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    ctx.on('event', first)
    task = asyncio.create_task(ctx.serial('event'))
    await entered.wait()
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()
    finally:
        await ctx.fiber.dispose()
