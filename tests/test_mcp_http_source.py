import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from dsh.core.abort import AbortController
from test_mcp_http_transport import ROOT, dispose, launch


@pytest.mark.asyncio
async def test_actual_source_http_sdk_wire_results_errors_and_close(tmp_path):
    output = tmp_path / 'source.json'
    directory = tmp_path / 'source-peers'
    directory.mkdir()
    environment = dict(os.environ, MCP_HTTP_OUTPUT=str(output), MCP_HTTP_DIRECTORY=str(directory),
        MCP_FIXTURE_PYTHON=os.sys.executable, MCP_HTTP_PEER=str(ROOT / 'scripts/oracles/mcp_http_peer.py'))
    source_run = subprocess.run([shutil.which('node'), '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run', '--config', str(ROOT / 'scripts/oracles/vitest.mcp-http-probe.config.mts')],
        cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
    output.with_suffix('.source.log').write_bytes(source_run.stdout + source_run.stderr)
    assert source_run.returncode == 0, source_run.stdout.decode('utf-8', errors='replace') + source_run.stderr.decode('utf-8', errors='replace')
    rows = json.loads(output.read_text(encoding='utf-8'))
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
