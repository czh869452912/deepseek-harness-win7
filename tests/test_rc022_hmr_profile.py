import asyncio

import pytest

from scripts.rc022_hmr_profile_probe import observe


@pytest.mark.asyncio
async def test_actual_profile_module_recomposition(tmp_path):
    rows = {row['mode']:row for row in await asyncio.wait_for(observe(tmp_path/'observations'), 25)}
    assert rows['unchanged']['same'] and rows['unchanged']['trace'] == []
    for mode in ('upgrade', 'shared'):
        assert rows[mode]['value'] == 2
        assert rows[mode]['trace'] == ['stop:1', 'start:2']
        assert not rows[mode]['same']
        assert rows[mode]['pending'] == []
    for mode in ('failure', 'syntax'):
        assert rows[mode]['failed'] and rows[mode]['value'] is None
        assert rows[mode]['trace'][0] == 'stop:1'
    assert rows['remove']['trace'] == ['stop:1'] and rows['remove']['value'] is None
    for mode, reason in [('host', 'host-module'), ('unmanaged', 'unmanaged-plugin')]:
        assert rows[mode]['same'] and rows[mode]['value'] == 1
        assert rows[mode]['pending'] == [dict(file='plugin.py', reason=reason)]
    assert rows['comparison-failure']['same'] and rows['comparison-failure']['restart'] == 'module-comparison'
    for mode in ('failure', 'syntax', 'remove'):
        assert rows[mode+'-recovered'] == dict(mode=mode+'-recovered', value=3, trace=['start:3'], pending=[])


@pytest.mark.asyncio
async def test_profile_reconcile_requires_transaction_and_profile():
    from dsh.cordis import Context
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService
    ctx = Context()
    await ctx.plugin(Loader)
    await ctx.plugin(TimerService)
    await ctx.plugin(ConfigWatcherService, dict(root=[]))
    try:
        hmr = ctx.get('hmr')
        with pytest.raises(RuntimeError, match='inside runExclusive'):
            await hmr.reconcileProfile()
        with pytest.raises(RuntimeError, match='requires profileContext'):
            await hmr.runExclusive(lambda: hmr.reconcileProfile())
    finally:
        await ctx.fiber.dispose()
