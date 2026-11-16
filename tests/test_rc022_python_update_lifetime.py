import asyncio
import json
from pathlib import Path
import threading

import pytest

from apps.cli import plugin as cli
from dsh.boot import python_plugins as store
from test_python_plugin_distribution import profile, close, PACKAGE
from test_rc022_python_package_acquire import registry_package
from test_rc022_python_package_backend import start
from test_rc022_python_package_update import next_version


@pytest.mark.asyncio
@pytest.mark.parametrize('owner', ['backend', 'host', 'waiter'])
async def test_native_update_ownership_through_disposal_and_abandoned_wait(profile, registry_package, owner):
    home, directory = profile
    state = registry_package
    host = await start(home, state)
    ctx, closed = host['ctx'], False
    backend, lease = ctx.profilePackages, ctx.pythonProfileLease
    result, waiter = None, None
    try:
        initial = await ctx.pluginManager.installBundle(PACKAGE)
        assert initial['application'] == 'applied', initial
        previous = json.loads((directory / 'package.json').read_text(encoding='utf-8'))['dsh']['pythonPlugins'][PACKAGE]
        next_version(state)
        state['pause'], state['entered'] = threading.Event(), threading.Event()
        update = ctx.pluginManager.updateBundle(PACKAGE, '0.2.0', dict(requestId='owned'))
        async def observe():
            return await update
        waiter = asyncio.create_task(observe())
        for _ in range(1500):
            if state['entered'].is_set():
                break
            await asyncio.sleep(.02)
        assert state['entered'].is_set() and PACKAGE in backend.updates
        if owner == 'backend':
            await asyncio.wait_for(backend.ctx.fiber.dispose(), 8)
            result = await asyncio.wait_for(waiter, 8)
            assert ctx.get('profilePackages') is None and backend.abort.signal.aborted
            assert result['result']['application'] == 'failed' and result['restore']['application'] == 'failed', result
            # The update retains its original backend even after its service is removed.
            assert 'This operation was aborted' in result['restore']['packageResult']['output'], result
        elif owner == 'host':
            await asyncio.wait_for(close(host), 8)
            closed = True
            result = await asyncio.wait_for(waiter, 8)
            assert lease.stream is None and backend.abort.signal.aborted
            assert result['result']['application'] in ('cancelled', 'failed') and result['restore']['application'] == 'failed', result
        else:
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
            assert PACKAGE in backend.updates and backend.operations and not backend.abort.signal.aborted
            state['pause'].set()
            result = await asyncio.wait_for(update, 45)
            assert result['result']['application'] == 'applied' and 'restore' not in result, result
            assert (await ctx.pluginManager.removeBundle(PACKAGE))['application'] == 'applied'
        assert not backend.updates and not backend.operations
        assert not (directory / '.dsh-python-downloads').exists() and not list(directory.rglob('run.json'))
        if owner != 'waiter':
            assert (Path(result['recovery']['path']) / 'recovery.json').is_file()
        else:
            assert not (directory / '.dsh-python-updates').exists()
    finally:
        if 'pause' in state:
            state['pause'].set()
        if not closed:
            await close(host)
        if waiter is not None and not waiter.done():
            await asyncio.gather(waiter, return_exceptions=True)
    if owner != 'waiter':
        assert cli.run_plugin('python-test', ['recover', result['recovery']['path']]) == 0
        restored = json.loads((directory / 'package.json').read_text(encoding='utf-8'))['dsh']['pythonPlugins'][PACKAGE]
        assert restored == previous and not Path(result['recovery']['path']).exists()
        store.uninstall(str(directory), PACKAGE)
