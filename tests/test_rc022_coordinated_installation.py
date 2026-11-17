"""Actual shipped rc022 installation, without candidate registry/anchor patches."""
import json
import pytest

from dsh.boot.profile_boot import run_profile, compose_profile
from dsh.core.abort import AbortController
from dsh.cordis.fiber import FiberState
from dsh.boot.profile import compose_entries


@pytest.mark.asyncio
async def test_shipped_web_mounts_every_preset_and_executes_python_ptc(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('DSH_TELEMETRY_MODE', 'DISABLED')
    app = await run_profile(dict(profile='web', dshHome=str(tmp_path / 'home'),
        args=['--host', '127.0.0.1', '--port', '0', '--no-open'], waitForExit=False))
    ctx = app['ctx']
    try:
        failed = [entry.id for entry in ctx.loader.entries()
                  if entry.fiber is not None and entry.fiber.state == FiberState.FAILED]
        assert not failed
        assert {row['id'] for row in (await ctx.agentPresets.remoteExportList())['presets']} == {'minimal', 'standard', 'ptc', 'cordis'}
        for preset in ['minimal', 'standard', 'ptc', 'cordis']:
            await ctx.sessionController.create(dict(sessionId='installed-' + preset,
                cwd=str(tmp_path), agentPreset=preset))
        agent = ctx.agents.get('installed-ptc')
        runtime = ctx.ptcRuntime
        assert runtime.language == 'python' and not runtime.retainsState
        result = await ctx.tools.execute(dict(agent=agent, signal=AbortController().signal,
            calls=[dict(type='tool-call', id='installed-code', name='run_code', arguments=json.dumps(
                dict(code='return await tools.schedule_list({})', description='Read schedule through installed Python PTC')))]))
        assert result['results'][0]['result'].is_error is False
        graph = ctx.clientModules.graph()
        assert graph['entries'] and graph['batches']
        assert ctx.typert.getPackage('@deepseek-ai/dsh-api-terminal-controller') is not None
    finally:
        app['shutdown'].shutdown(0)
        await app['shutdown'].wait()


@pytest.mark.asyncio
async def test_shipped_profiles_compose_explicit_win7_adaptations(tmp_path):
    for profile in ['minimal', 'standard', 'creative', 'acp', 'sdk', 'web', 'headless']:
        composed = await compose_profile(profile, dsh_home=str(tmp_path / profile))
        entries = compose_entries([composed.all_patches()])
        assert entries
        rows = {entry['id']: entry for entry in entries}
        if profile in ['minimal']:
            assert rows['tool-fs']['disabled'] and rows['tool-working-directory']['disabled']
            assert rows['str-replace-editor']['name'] == '@deepseek-ai/dsh-tool-str-replace-editor'
        else:
            assert rows['ptc-runtime']['disabled']
            assert rows['win7-ptc-runtime']['name'] == '@deepseek-win7/dsh-ptc-runtime-python'
