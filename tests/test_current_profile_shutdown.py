"""Profile shutdown drains Agent-owned writes while their providers are live."""
import pytest

from dsh.boot.profile_boot import run_profile


@pytest.mark.asyncio
async def test_web_shutdown_drains_live_agents_and_projection_writes(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('DSH_TELEMETRY_MODE', 'DISABLED')
    running = await run_profile(dict(profile='web', dshHome=str(tmp_path / 'home'),
                                    args=['--no-open', '--port', '0'], waitForExit=False))
    ctx = running['ctx']
    cache = ctx.get('sessionProjectionCache')
    persistence = ctx.get('sessionPersistence')
    handles = []
    try:
        for index in range(4):
            handle = await ctx.get('agents').create(dict(sessionId='shutdown-%s' % index))
            handles.append(handle)
            handle.agent.session.append('session/title', dict(title='durable title %s' % index,
                source=dict(kind='user'), messageSeqs=[]))
    finally:
        running['shutdown'].shutdown(0)
        await running['shutdown'].wait()
    assert not persistence.tracker.writers
    assert not cache.tasks and not cache.writes
    assert 'Checkpoint write failed' not in caplog.text
    assert 'Exception' not in caplog.text
    for index, handle in enumerate(handles):
        reader = await persistence.open(handle.agent.id, 'read')
        try:
            assert any(event['type'] == 'session/title' and event['data']['title'] == 'durable title %s' % index
                       for event in (await reader.read())['events'])
        finally:
            await reader.close()
