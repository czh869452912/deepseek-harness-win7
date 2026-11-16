import json

import pytest

from dsh.boot.profile_boot import run_profile
from dsh.boot.startup import inactive_entries
from dsh.typert.dispatch import RemoteDispatcher


@pytest.mark.asyncio
async def test_canonical_web_composes_current_providers_and_separates_public_url(tmp_path, monkeypatch):
    monkeypatch.setenv('DSH_HOME', str(tmp_path))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    running = await run_profile(dict(profile='web', dshHome=str(tmp_path),
        args=['--no-open', '--port', '0', '--public-url', 'https://advertised.example/ui',
              '--trusted-host', 'gateway.example'], waitForExit=False))
    ctx = running['ctx']
    try:
        services = ['webApp', 'remoteAccess', 'workingDirectory', 'fileUploads', 'mcpManager', 'mcpResources', 'workspaceChanges', 'pluginManager']
        assert [name for name in services if ctx.get(name) is None] == []
        assert await inactive_entries(ctx) == []
        assert ctx.get('webRuntime') is None
        assert ctx.webServer.protocol == 'http:'
        assert ctx.webApp.getAdvertisedUrl() == 'https://advertised.example/ui/'
        assert ctx.connection.trusted_hosts == ['gateway.example']
        assert ctx.mcpManager.list() == []
        entries = list(ctx.loader.entries())
        row = next(item for item in entries if item.options.get('id') == 'mcp-manager')
        assert row.fiber is not None
        management_tool = next(item for item in entries if item.options.get('id') == 'tool-plugin-manager')
        assert management_tool.options.get('disabled') is True
        assert any(item.options.get('id') == 'harness-dev-context' and item.fiber is not None for item in entries)
        with pytest.raises(RuntimeError, match='unknown server') as rejected:
            await RemoteDispatcher(ctx).invoke(dict(namespace='mcpManager', method='restart', args=dict(name='missing')))
        result = str(rejected.value)
        (tmp_path/'web-composition-observations.json').write_text(json.dumps(dict(
            services=services, advertised=ctx.webApp.getAdvertisedUrl(),
            trusted=ctx.connection.trusted_hosts, missingRestart=result), indent=2), encoding='utf-8')
    finally:
        running['shutdown'].shutdown(0)
        await running['shutdown'].wait()
    assert ctx.get('webApp') is None
    assert ctx.get('mcpManager') is None
