"""Canonical Web profile failure boundary until its real providers are complete.

Static HTML from the retired harness composition is not Web acceptance. These
cases exercise run_profile and ensure partial startup advertises no usable URL
and leaves no listening server behind. Positive runtime transport coverage is
in test_canonical_web_runtime.py.
"""
import asyncio

import pytest

from dsh.boot.profile_boot import run_profile
from dsh.host.webserver.webserver import WebServerService


@pytest.mark.asyncio
@pytest.mark.parametrize('telemetry_disabled', [False, True])
async def test_formal_web_profile_fails_cleanly_on_remaining_providers(tmp_path, monkeypatch, capsys, telemetry_disabled):
    if telemetry_disabled:
        monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    else:
        monkeypatch.delenv('DSH_TELEMETRY_DISABLED', raising=False)
    servers = []
    start = WebServerService.start
    async def capture_start(server):
        await start(server)
        servers.append(server)
    monkeypatch.setattr(WebServerService, 'start', capture_start)
    with pytest.raises(RuntimeError, match='plugin tree failed to load') as raised:
        await asyncio.wait_for(run_profile(dict(profile='web', dshHome=str(tmp_path),
            args=['--no-open', '--port', '0'], waitForExit=False)), 30)
    for package in ('api-session-controller', 'api-workspace-controller',
                    'cordis-host-runner', 'session-reference', 'session-log-export'):
        assert "Cannot find module '@deepseek-ai/dsh-%s'" % package in str(raised.value)
    assert ("Cannot find module '@deepseek-ai/dsh-session-telemetry-otel'" in str(raised.value)) is (not telemetry_disabled)
    assert 'dsh web: http' not in capsys.readouterr().out
    assert servers and all(not server._is_running and not server._connections for server in servers)
    for server in servers:
        with pytest.raises(OSError):
            await asyncio.wait_for(asyncio.open_connection('127.0.0.1', server.port), 3)
