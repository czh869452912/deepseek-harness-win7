import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from dsh.mcp.stdio_client import McpError
from dsh.core.abort import AbortController
from dsh.cordis.errors import ThrownValueError
from dsh.mcp.transport import StdioMcpTransport


SERVER = '''import json,os,sys
for line in sys.stdin:
    packet=json.loads(line)
    method=packet.get("method")
    if method=="notifications/initialized":
        print(json.dumps({"jsonrpc":"2.0","method":"notifications/tools/list_changed"}),flush=True)
    if "id" not in packet:
        continue
    reply={"jsonrpc":"2.0","id":packet["id"]}
    if method=="initialize":
        reply["result"]={"protocolVersion":os.environ.get("MCP_VERSION","2025-11-25"),
            "capabilities":{"tools":{}},"serverInfo":{"name":"controlled","version":"1.0"}}
    elif method=="tools/list":
        reply["result"]={"tools":[{"name":"echo","inputSchema":{"type":"object"}}]}
    elif method=="tools/call":
        args=packet["params"]["arguments"]
        if args.get("wait"):
            continue
        if args.get("error"):
            reply["error"]={"code":-32602,"message":"controlled rejection","data":{"invalid":True}}
        else:
            reply["result"]={"content":[{"type":"text","text":args.get("text","echo")}],
                "structuredContent":{"inherited":os.environ.get("CONTROLLED_API_KEY"),
                    "explicit":os.environ.get("EXPLICIT_TOKEN"),"stale":os.environ.get("DSH_STALE")}}
    else:
        reply["result"]={}
    print(json.dumps(reply),flush=True)
'''


@pytest.fixture
def server(tmp_path):
    path = tmp_path / 'server.py'
    path.write_text(SERVER, encoding='utf-8')
    return path


@pytest.mark.asyncio
async def test_missing_executable_rejects_connect_and_cannot_invent_tools(tmp_path):
    client = StdioMcpTransport(str(tmp_path / 'missing.exe'))
    with pytest.raises(McpError, match='Connection closed'):
        await client.connect()
    for operation in (client.list_tools(), client.call_tool('absent', {})):
        with pytest.raises(RuntimeError, match='Not connected'):
            await operation
    await client.close()
    assert client.proc is None and not client._pending


@pytest.mark.asyncio
async def test_actual_handshake_tools_correlation_notifications_and_scrubbed_environment(server, monkeypatch):
    monkeypatch.setenv('CONTROLLED_API_KEY', 'must-not-inherit')
    monkeypatch.setenv('DSH_STALE', 'must-not-inherit')
    client = StdioMcpTransport(sys.executable, [str(server)], env={'EXPLICIT_TOKEN': 'fixture-only'})
    notifications, changed = [], asyncio.Event()
    def notified(packet):
        notifications.append(packet)
        changed.set()
    client.on_notification = notified
    try:
        assert await client.connect() is client
        await asyncio.wait_for(changed.wait(), 2)
        assert client.protocol_version == '2025-11-25'
        assert client.server_info == {'name': 'controlled', 'version': '1.0'}
        assert notifications == [{'method': 'notifications/tools/list_changed'}]
        assert await client.list_tools() == {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]}
        outputs = await asyncio.gather(*(client.call_tool('echo', {'text': str(index)}) for index in range(8)))
        assert [result['content'][0]['text'] for result in outputs] == [str(index) for index in range(8)]
        assert outputs[0]['structuredContent'] == {'inherited': None, 'stale': None, 'explicit': 'fixture-only'}
        with pytest.raises(McpError) as failure:
            await client.call_tool('echo', {'error': True})
        assert failure.value.code == -32602 and failure.value.data == {'invalid': True}
        assert not client._pending
    finally:
        await client.close()
    assert client.proc.returncode == 0 and client.stderr == b''


@pytest.mark.asyncio
async def test_invalid_negotiation_closes_actual_process_before_exposing_client(server):
    client = StdioMcpTransport(sys.executable, [str(server)], env={'MCP_VERSION': 'unsupported'})
    with pytest.raises(ValueError, match='not supported'):
        await client.connect()
    assert client.proc.returncode == 0 and not client._pending


@pytest.mark.asyncio
async def test_stdout_eof_is_not_process_close_before_process_exit():
    eof, exit_observed, exited = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Reader:
        async def read(self, size):
            eof.set()
            return b''
    async def wait():
        exit_observed.set()
        await exited.wait()
        return 0
    client = StdioMcpTransport('controlled')
    client.proc = SimpleNamespace(stdout=Reader(), wait=wait)
    closed = []
    client.on_close = lambda: closed.append(True)
    reader = asyncio.create_task(client._read())
    try:
        await asyncio.wait_for(exit_observed.wait(), 2)
        assert eof.is_set() and closed == [] and not reader.done()
    finally:
        exited.set()
        await asyncio.wait_for(reader, 2)
    assert closed == [True] and reader.done()


@pytest.mark.asyncio
async def test_abort_signal_reason_is_preserved_and_listener_detached(server):
    client = StdioMcpTransport(sys.executable, [str(server)])
    await client.connect()
    controller = AbortController()
    pending = asyncio.create_task(client.request({'method': 'tools/call', 'params': {
        'name': 'echo', 'arguments': {'wait': True}}}, signal=controller.signal))
    async def admitted():
        while not client._pending:
            await asyncio.sleep(0)
    try:
        await asyncio.wait_for(admitted(), 2)
        controller.abort('controlled cancel')
        with pytest.raises(McpError, match='controlled cancel') as failure:
            await pending
        assert failure.value.code == -32001 and not client._pending and not controller.signal._listeners
        with pytest.raises(ThrownValueError) as aborted:
            await client.request({'method': 'tools/list'}, signal=controller.signal)
        assert aborted.value.value == 'controlled cancel'
    finally:
        await client.close()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['dispose', 'cancel-connect'])
async def test_spawn_is_owned_before_await_and_late_process_is_reaped(server, monkeypatch, reason):
    original = asyncio.create_subprocess_exec
    admitted, release = asyncio.Event(), asyncio.Event()
    async def delayed_spawn(*args, **kwargs):
        admitted.set()
        await release.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed_spawn)
    client = StdioMcpTransport(sys.executable, [str(server)])
    connecting = asyncio.create_task(client.connect())
    await asyncio.wait_for(admitted.wait(), 2)
    if reason == 'cancel-connect':
        connecting.cancel()
    closing = asyncio.create_task(client.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    try:
        await asyncio.wait_for(closing, 3)
        with pytest.raises((McpError, asyncio.CancelledError)):
            await connecting
        assert client.proc.returncode == 0 and not client._pending
        assert client._reader.done() and client._stderr.done()
    finally:
        release.set()
        await client.close()
        await asyncio.gather(connecting, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [
    {}, {'tools': None}, {'tools': [None]}, {'tools': [{'name': True, 'inputSchema': {'type': 'object'}}]},
    {'tools': [{'name': 'unsafe'}]}, {'tools': [{'name': 'unsafe', 'inputSchema': {'type': 'array'}}]},
    {'tools': [{'name': 'unsafe', 'inputSchema': {'type': 'object', 'required': [1]}}]},
    {'tools': [{'name': 'unsafe', 'inputSchema': {'type': 'object', 'properties': {'value': False}}}]},
    {'tools': [{'name': 'unsafe', 'inputSchema': {'type': 'object'}, 'description': 5}]},
    {'tools': [{'name': 'unsafe', 'inputSchema': {'type': 'object'}, 'outputSchema': {'type': 'string'}}]},
    {'tools': [], 'nextCursor': 42},
])
async def test_actual_peer_cannot_publish_malformed_tool_definitions(server, result):
    replacement = 'if method=="tools/list":\n        reply["result"]=%r\n    print(json.dumps(reply),flush=True)' % result
    server.write_text(SERVER.replace('print(json.dumps(reply),flush=True)', replacement), encoding='utf-8')
    client = StdioMcpTransport(sys.executable, [str(server)])
    await client.connect()
    try:
        with pytest.raises(ValueError, match='Invalid MCP'):
            await client.request({'method': 'tools/list'})
        assert not client._pending
    finally:
        await client.close()
    assert client.proc.returncode == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('capabilities', [{'tools': False}, {'resources': []}, {'tools': {'listChanged': 'yes'}}])
async def test_actual_invalid_initialize_capability_is_rejected_and_owned_child_exits(server, capabilities):
    replacement = 'if method=="initialize":\n        reply["result"]["capabilities"]=%r\n    print(json.dumps(reply),flush=True)' % capabilities
    server.write_text(SERVER.replace('print(json.dumps(reply),flush=True)', replacement), encoding='utf-8')
    client = StdioMcpTransport(sys.executable, [str(server)])
    with pytest.raises(ValueError, match='Invalid MCP capability'):
        await client.connect()
    assert client.proc.returncode == 0 and not client._pending


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [None, False, 0, {}, {'invalid': True}])
async def test_error_data_is_not_replaced_by_absence(server, data):
    replacement = 'if method=="tools/call":\n        reply={"jsonrpc":"2.0","id":packet["id"],"error":{"code":-32602.0,"message":"controlled rejection","data":%r}}\n    print(json.dumps(reply),flush=True)' % data
    server.write_text(SERVER.replace('print(json.dumps(reply),flush=True)', replacement), encoding='utf-8')
    client = StdioMcpTransport(sys.executable, [str(server)])
    await client.connect()
    try:
        with pytest.raises(McpError) as rejected:
            await client.call_tool('echo', {})
        assert rejected.value.has_data and rejected.value.data == data
        assert str(rejected.value) == 'MCP error -32602: controlled rejection'
        assert rejected.value.name == 'McpError' and rejected.value.message == str(rejected.value)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_owned_notification_callback_is_drained_and_close_fires_once(server):
    client = StdioMcpTransport(sys.executable, [str(server)])
    admitted, disposed = asyncio.Event(), asyncio.Event()
    closed = []
    async def notification(packet):
        admitted.set()
        try:
            await asyncio.get_running_loop().create_future()
        finally:
            disposed.set()
    client.on_notification = notification
    client.on_close = lambda: closed.append(True)
    await client.connect()
    await asyncio.wait_for(admitted.wait(), 2)
    await asyncio.wait_for(asyncio.gather(client.close(), client.close()), 3)
    assert disposed.is_set() and closed == [True] and not client._callbacks


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['close', 'cancel', 'timeout'])
async def test_owned_pending_request_settles_and_late_work_cannot_survive_shutdown(server, reason):
    client = StdioMcpTransport(sys.executable, [str(server)])
    await client.connect()
    signal = asyncio.Event()
    waiting = asyncio.create_task(client.request({'method': 'tools/call', 'params': {
        'name': 'echo', 'arguments': {'wait': True}}}, signal=signal, timeout=30 if reason == 'timeout' else 60000))
    try:
        async def admitted():
            while not client._pending:
                await asyncio.sleep(0)
        await asyncio.wait_for(admitted(), 2)
        if reason == 'close':
            await client.close()
            with pytest.raises(McpError, match='Connection closed'):
                await waiting
        elif reason == 'cancel':
            signal.set()
            with pytest.raises(asyncio.CancelledError):
                await waiting
        else:
            with pytest.raises(McpError, match='timed out'):
                await waiting
        assert not client._pending
    finally:
        await client.close()
        await asyncio.gather(waiting, return_exceptions=True)
    assert client.proc.returncode == 0 and client._reader.done() and client._stderr.done()
