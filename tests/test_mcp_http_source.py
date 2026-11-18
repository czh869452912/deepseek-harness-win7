import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from dsh.core.abort import AbortController
from test_mcp_http_transport import ROOT, dispose, launch
from evidence_fixtures import read_member
from release_gate_fixtures import ARCHIVE


@pytest.mark.asyncio
async def test_historical_source_http_sdk_wire_results_errors_and_close(tmp_path):
    rows = read_member(ARCHIVE, 'full-gate-root.zip!/mcp-http-paired.ts.json')
    assert len(rows) == 16
    for expected in rows:
        mode = expected['mode']
        native_directory = tmp_path / mode
        native_directory.mkdir()
        process, records, client = await launch(mode, native_directory)
        row = {'mode': mode, 'notifications': []}
        client.on_notification = row['notifications'].append
        try:
            await client.connect()
            row['server'] = client.server_info
            for index in range(500):
                if Path(str(records) + '.get').exists():
                    break
                await asyncio.sleep(0.001)
            assert Path(str(records) + '.get').exists()
            row['tools'] = await client.list_tools()
            controller = AbortController()
            pending = asyncio.create_task(client.request({'method': 'tools/call', 'params': {
                'name': 'echo', 'arguments': {'text': '中文 controlled'}}}, signal=controller.signal,
                timeout=100 if mode == 'timeout' else 60000))
            for index in range(100):
                if Path(str(records) + '.call').exists():
                    break
                await asyncio.sleep(0.001)
            if mode == 'cancel':
                controller.abort('controlled cancellation')
            elif mode == 'close-pending':
                await client.close()
            row['result'] = await pending
            for index in range(100):
                if Path(str(records) + '.get').exists():
                    break
                await asyncio.sleep(0.001)
            if mode in ('session', 'delete-405'):
                await client.terminate_session()
        except Exception as error:
            row['error'] = {'name': getattr(error, 'name', 'Error'), 'message': str(error)}
            if hasattr(error, 'code'):
                row['error']['code'] = error.code
            if getattr(error, 'has_data', False):
                row['error']['data'] = error.data
        finally:
            admitted = True
            if mode in ('cancel', 'timeout'):
                for index in range(500):
                    if Path(str(records) + '.cancel').exists():
                        break
                    await asyncio.sleep(0.001)
                admitted = Path(str(records) + '.cancel').exists()
            await dispose(process, client)
            assert admitted
        row.update(frames=json.loads(records.read_text(encoding='utf-8')),
            closed=client._closed and not client._pending and not client._tasks and not client._writers,
            reaped=process.returncode == 0)
        assert row == expected, mode
