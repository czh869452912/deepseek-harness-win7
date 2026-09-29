"""Retired flat-harness guarantees exercised through the formal profile entry."""
import asyncio
import pytest
from dsh.boot.profile_boot import run_profile
from canonical_web_fixture import web_context, close_web_context


@pytest.mark.asyncio
async def test_missing_profile_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    with pytest.raises(Exception, match='nonexistent'):
        await run_profile(dict(profile='nonexistent-preset-mode-12345', dshHome=str(tmp_path), waitForExit=False))


@pytest.mark.asyncio
async def test_profile_applies_overlay(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    patch = tmp_path / 'overlay.yml'
    patch.write_text('- id: session-query-sqlite\n  config:\n    openAt: first-search\n', encoding='utf-8')
    result = await run_profile(dict(profile='web', dshHome=str(tmp_path), patchFiles=[str(patch)], args=['--no-open', '--port', '0'], waitForExit=False))
    try:
        assert result['ctx'].get('sessionQuery').open_at == 'first-search'
    finally:
        result['shutdown'].shutdown(0)
        await result['shutdown'].wait()


@pytest.mark.asyncio
async def test_missing_overlay_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    with pytest.raises(Exception, match='missing-overlay'):
        await run_profile(dict(profile='web', dshHome=str(tmp_path), patchFiles=[str(tmp_path / 'missing-overlay.yml')], args=['--no-open', '--port', '0'], waitForExit=False))


@pytest.mark.asyncio
async def test_formal_home_and_dormant_search(tmp_path):
    ctx = await web_context(tmp_path)
    try:
        assert Path(ctx.get('dshHomePath')('sessions')) == tmp_path / 'sessions'
        assert ctx.get('sessionQuery').open_at == 'never'
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_activation_failure_disposes_partial_profile(tmp_path, monkeypatch):
    from dsh.host.webserver.webserver import WebServerPlugin
    seen = []
    def broken(self, ctx):
        seen.append(ctx)
        raise RuntimeError('web-activation-test-failure')
    monkeypatch.setattr(WebServerPlugin, 'apply', broken)
    with pytest.raises(RuntimeError, match='web-activation-test-failure'):
        await web_context(tmp_path)
    assert seen
    root = seen[0].root
    assert root.registry.list_fibers() == []
    assert root.fiber.settlement_tasks() == []
    assert root.get('webServer') is None
    assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task() and not task.done()]


from pathlib import Path
