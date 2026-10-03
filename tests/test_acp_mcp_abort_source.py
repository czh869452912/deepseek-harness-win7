import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from dsh.core.abort import AbortController
from scripts.acp_mcp_journey import process_exited
from scripts.acp_mcp_oracle import canonical
from test_acp_session_controls import boot_profile, stop_profile
from test_mcp_stdio_transport import SERVER


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_actual_source_and_native_mcp_startup_abort_wait_for_late_handshake_then_reap(tmp_path, monkeypatch):
    node = shutil.which('node')
    assert node, 'ACP source cancellation observer requires Node'
    server = tmp_path / 'blocked.py'
    controlled = SERVER.replace('import json,os,sys', 'import json,os,sys,pathlib,time').replace(
        '    if method=="initialize":', '    if method=="initialize":\n'
        '        pathlib.Path(sys.argv[1]).write_text("ready",encoding="utf-8")\n'
        '        while not pathlib.Path(sys.argv[2]).exists():\n'
        '            time.sleep(0.01)')
    controlled += '\npathlib.Path(sys.argv[3]).write_text(json.dumps({"closed":True,"pid":os.getpid()}),encoding="utf-8")\n'
    server.write_text(controlled, encoding='utf-8')
    output, marker, release, child_record = [tmp_path / name for name in ['source.json', 'marker', 'release', 'child.json']]
    completed = subprocess.run([node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run', '--config', str(ROOT / 'scripts/oracles/vitest.acp-mcp-abort.config.mts')], cwd=str(ROOT),
        env=dict(os.environ, ACP_MCP_ABORT_OUTPUT=str(output), ACP_MCP_MARKER=str(marker),
            ACP_MCP_RELEASE=str(release), ACP_MCP_CHILD_RECORD=str(child_record),
            ACP_MCP_PEER=str(server), ACP_MCP_PYTHON=sys.executable), capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stdout.decode('utf-8', 'replace') + completed.stderr.decode('utf-8', 'replace')
    expected = json.loads(output.read_text(encoding='utf-8'))
    assert expected['childClosed'] is True and type(expected['childPid']) is int and process_exited(expected['childPid'])
    expected.pop('childPid')
    assert canonical(expected) == canonical({'beforeAgents': 0, 'beforeRelease': False,
        'result': {'rejected': True, 'name': 'Error', 'message': 'controlled setup abort'},
        'finalAgents': 0, 'finalTools': [], 'childClosed': True})
    marker.unlink()
    release.unlink()
    child_record.unlink()
    runtime, bridge, unused = await boot_profile(tmp_path, 'jsonl', monkeypatch)
    ctx, controller = runtime['ctx'], AbortController()
    pending = asyncio.create_task(bridge.new_session(ctx, {'cwd': str(tmp_path), 'mcpServers': [{
        'name': 'blocked', 'command': sys.executable,
        'args': [str(server), str(marker), str(release), str(child_record)], 'env': []}]}, controller.signal))
    observed = {}
    try:
        async def admitted():
            while not marker.exists():
                await asyncio.sleep(0.01)
        await asyncio.wait_for(admitted(), 5)
        observed['beforeAgents'] = len(ctx.get('agents').list())
        controller.abort(RuntimeError('controlled setup abort'))
        await asyncio.sleep(0.05)
        observed['beforeRelease'] = pending.done()
        release.write_text('release', encoding='utf-8')
        try:
            await asyncio.wait_for(pending, 10)
            observed['result'] = {'rejected': False}
        except RuntimeError as error:
            observed['result'] = {'rejected': True, 'name': 'Error', 'message': str(error)}
        record = json.loads(child_record.read_text(encoding='utf-8'))
        assert type(record['pid']) is int and process_exited(record['pid'])
        observed.update(finalAgents=len(ctx.get('agents').list()), finalTools=ctx.get('tools').schemas(), childClosed=record['closed'])
        assert canonical(observed) == canonical(expected)
    finally:
        release.write_text('release', encoding='utf-8')
        await asyncio.gather(pending, return_exceptions=True)
        await stop_profile(runtime)
