import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from dsh.mcp.connection import McpConnection
from historical_mcp_modules import observe_module


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_sealed_legacy_supervisor_with_current_helpers_and_retained_consumer(tmp_path, monkeypatch):
    output = tmp_path / 'supervisor.json'
    rows = observe_module('supervisor', output, dict(MCP_SUPERVISOR_OUTPUT=str(output)))
    assert len(rows) == 9
    for row in rows:
        scenario, trace, logs, registered, peers = row['scenario'], [], [], set(), []
        fetches = 0
        class Peer:
            def __init__(self):
                self.on_close = self.on_notification = None
            async def connect(self):
                trace.append(['connect'])
                if scenario.startswith('connect-failure'):
                    raise RuntimeError('controlled connect failure')
            async def close(self):
                trace.append(['close'])
                self.on_close()
            async def request(self, packet):
                nonlocal fetches
                trace.append(['fetch', packet['method']])
                fetches += 1
                if scenario == 'notification-failure' and fetches > 1:
                    raise RuntimeError('controlled fetch failure')
                return {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]}
        def factory(config):
            peer = Peer()
            peers.append(peer)
            trace.append(['create', len(peers)])
            return peer
        monkeypatch.setattr('dsh.mcp.connection.create_transport', factory)
        class Tools:
            def register(self, definition):
                trace.append(['register', definition['name']])
                if scenario.startswith('registration-'):
                    raise RuntimeError('controlled registration failure')
                registered.add(definition['name'])
                def dispose():
                    trace.append(['unregister', definition['name']])
                    registered.discard(definition['name'])
                return dispose
        class Context:
            logger = SimpleNamespace(**{level: lambda message, level=level: logs.append([level, message])
                for level in ('warn', 'error', 'info')})
            def get(self, name):
                return Tools() if name == 'tools' else None
        enabled = scenario in ('connect-failure-exhaust', 'close-retry')
        handle = McpConnection(Context(), {'serverName': 'controlled', 'failOnStartupError': scenario == 'registration-throw'},
            {'enabled': enabled, 'initialDelayMs': 1, 'maxDelayMs': 1000, 'maxAttempts': 1})
        try:
            outcome = await handle.ready
            if scenario.startswith('close-'):
                peers[0].on_close()
            if scenario.startswith('notification-'):
                await peers[0].on_notification({'method': 'notifications/tools/list_changed'})
            if enabled:
                for index in range(100):
                    if len(peers) >= 2 and handle._start_task.done():
                        break
                    await asyncio.sleep(0.001)
            before = sorted(registered)
        finally:
            await handle.dispose()
        actual = {'scenario': scenario, 'outcome': {name: {'name': 'Error', 'message': str(error)}
            for name, error in outcome.items()}, 'before': before,
            'after': sorted(registered), 'trace': trace, 'logs': logs}
        assert actual == row
