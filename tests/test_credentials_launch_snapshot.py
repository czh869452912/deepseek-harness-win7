import os

import pytest

from dsh.boot.app_boot import LaunchEnvironmentSnapshot as BootSnapshot
from dsh.boot.profile_boot import run_profile
from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.credentials.credentials_local import CredentialsService
from dsh.typert.dispatch import RemoteDispatcher
from dsh.typert.remote import TypertRemoteFailure


@pytest.mark.parametrize('snapshot_type', [BootSnapshot, LaunchEnvironmentSnapshot])
def test_canonical_snapshot_owns_reference_precedence_and_writes(tmp_path, monkeypatch, snapshot_type):
    ref = 'SNAPSHOT_TEST_KEY'
    monkeypatch.setenv(ref, 'ambient-after-launch')
    ctx = Context()
    ctx.set_service('launchEnvironment', snapshot_type([
        dict(source='process', values={}),
        dict(source='project-env', values={ref: 'project'}, path='project.env'),
        dict(source='user-env', values={ref: 'user'}, path='user.env'),
    ]))
    credentials = CredentialsService(ctx, credentials_file=str(tmp_path / 'credentials.yaml'))
    assert credentials.resolve(ref).value == 'project'
    assert credentials.describe(ref) == dict(configured=True, source='project-env', writable=True)
    credentials.set(ref, 'stored')
    assert credentials.resolve(ref).value == 'stored'
    credentials.unset(ref)
    assert credentials.resolve(ref).value == 'project'
    ctx.set_service('launchEnvironment', snapshot_type([
        dict(source='process', values={ref: 'inherited-at-launch'}),
    ]))
    monkeypatch.delenv(ref)
    assert credentials.resolve(ref).value == 'inherited-at-launch'
    assert credentials.describe(ref) == dict(configured=True, source='env', writable=False)
    with pytest.raises(ValueError, match='supplied read-only'):
        credentials.set(ref, 'refused')
    with pytest.raises(ValueError, match='supplied read-only'):
        credentials.unset(ref)


@pytest.mark.asyncio
async def test_web_credentials_remote_uses_launch_layers_and_preserves_them_on_restart(tmp_path, monkeypatch):
    inherited, fallback = 'WEB_LAUNCH_KEY', 'WEB_DOTENV_KEY'
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    monkeypatch.setenv(inherited, 'inherited-fixture')
    snapshot = BootSnapshot([
        dict(source='process', values=dict(os.environ)),
        dict(source='project-env', values={fallback: 'project-fixture'}),
        dict(source='user-env', values={fallback: 'user-fixture'}),
    ])
    monkeypatch.setenv(inherited, 'changed-after-launch')
    monkeypatch.setenv(fallback, 'absent-from-launch')

    async def boot():
        return await run_profile(dict(profile='web', dshHome=str(tmp_path), environment=snapshot,
                                     args=['--no-open', '--port', '0'], waitForExit=False))

    async def call(ctx, method, **args):
        return await RemoteDispatcher(ctx).invoke(dict(namespace='credentials', method=method, args=args))

    first = await boot()
    try:
        ctx = first['ctx']
        info = await call(ctx, 'describe', refs=[inherited, fallback])
        assert info == {
            inherited: dict(configured=True, source='env', writable=False),
            fallback: dict(configured=True, source='project-env', writable=True),
        }
        assert ctx.get('credentials').resolve(inherited).value == 'inherited-fixture'
        with pytest.raises(TypertRemoteFailure):
            await call(ctx, 'set', ref=inherited, value='refused')
        await call(ctx, 'set', ref=fallback, value='stored-fixture')
        assert ctx.get('credentials').resolve(fallback).value == 'stored-fixture'
    finally:
        first['shutdown'].shutdown(0)
        await first['shutdown'].wait()

    restarted = await boot()
    try:
        ctx = restarted['ctx']
        assert ctx.get('credentials').resolve(fallback).value == 'stored-fixture'
        await call(ctx, 'unset', ref=fallback)
        assert ctx.get('credentials').resolve(fallback).value == 'project-fixture'
        assert (await call(ctx, 'describe', refs=[fallback]))[fallback]['source'] == 'project-env'
    finally:
        restarted['shutdown'].shutdown(0)
        await restarted['shutdown'].wait()
