import asyncio
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(sys.argv[2]).resolve() if __name__ == '__main__' and len(sys.argv) > 2 else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import dsh
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.tools import ToolsService
from dsh.mcp.client import McpClientPlugin
from dsh.mcp.transport import StreamableHttpMcpTransport


MODES = ('json', 'json-batch', 'json-bom', 'post-sse', 'sse-bom', 'get-sse', 'session', 'delete-405',
    'status-401', 'unexpected-content', 'missing-content', 'peer-error', 'cancel', 'timeout', 'close-pending', 'invalid-envelope')
PEER = Path(__file__).with_name('mcp_http_peer.py')


async def admitted(path):
    deadline = asyncio.get_running_loop().time() + 5
    while not path.exists():
        if asyncio.get_running_loop().time() > deadline:
            raise RuntimeError('Controlled HTTP request not admitted: ' + path.name)
        await asyncio.sleep(0.001)


async def launch(mode, directory):
    records = directory / (mode + '.json')
    process = await asyncio.create_subprocess_exec(sys.executable, str(PEER), mode, str(records),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        url = (await asyncio.wait_for(process.stdout.readline(), 5)).decode('utf-8').strip()
        if not url.startswith('http://127.0.0.1:'):
            raise RuntimeError('Controlled HTTP peer failed to start')
        return process, records, url
    except BaseException:
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 5)
        raise


async def finish(process, client):
    try:
        if client is not None:
            await client.close()
    finally:
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 5)
    if process.returncode != 0 or await process.stderr.read():
        raise RuntimeError('Controlled HTTP peer did not close cleanly')


async def observe(mode, directory):
    process, records, url = await launch(mode, directory)
    client = StreamableHttpMcpTransport(url, {'Authorization': 'controlled-local'})
    row = {'mode': mode, 'notifications': []}
    client.on_notification = row['notifications'].append
    try:
        await client.connect()
        row['server'] = client.server_info
        await admitted(Path(str(records) + '.get'))
        row['tools'] = await client.list_tools()
        controller = AbortController()
        pending = asyncio.create_task(client.request({'method': 'tools/call', 'params': {
            'name': 'echo', 'arguments': {'text': '中文 controlled'}}}, signal=controller.signal,
            timeout=100 if mode == 'timeout' else 60000))
        try:
            await admitted(Path(str(records) + '.call'))
            if mode == 'cancel':
                controller.abort('controlled cancellation')
            elif mode == 'close-pending':
                await client.close()
            row['result'] = await pending
        finally:
            if not pending.done():
                await client.close()
            await asyncio.gather(pending, return_exceptions=True)
        if mode in ('session', 'delete-405'):
            await client.terminate_session()
    except Exception as error:
        row['error'] = {'name': getattr(error, 'name', 'Error'), 'message': str(error)}
        if hasattr(error, 'code'):
            row['error']['code'] = error.code
        if getattr(error, 'has_data', False):
            row['error']['data'] = error.data
    finally:
        try:
            if mode in ('cancel', 'timeout'):
                await admitted(Path(str(records) + '.cancel'))
        finally:
            await finish(process, client)
    row.update(frames=json.loads(records.read_text(encoding='utf-8')),
        closed=client._closed and not client._pending and not client._tasks and not client._writers,
        reaped=process.returncode == 0)
    return row


async def consumer(directory):
    process, records, url = await launch('session', directory)
    ctx = Context()
    tools = ToolsService(ctx)
    ctx.set_service('tools', tools)
    plugin = McpClientPlugin({'transport': 'streamable-http', 'serverName': 'owned', 'url': url,
        'headers': {'Authorization': 'controlled-local'}, 'failOnStartupError': True, 'reconnect': {'enabled': False}})
    client = None
    try:
        fiber = ctx.plugin(plugin)
        await fiber
        client = plugin.connection.client
        registered = tools.has_tool('mcp__owned__echo')
        output = await tools.execute_tool('mcp__owned__echo', {'text': 'controlled consumer'})
        await fiber.dispose()
    finally:
        try:
            await ctx.fiber.dispose()
        finally:
            await finish(process, client)
    return {'registered': registered, 'output': output, 'retired': not tools.has_tool('mcp__owned__echo'),
        'closed': client._closed, 'writers': len(client._writers), 'tasks': len(client._tasks),
        'pending': len(client._pending), 'childExited': process.returncode == 0}


async def main():
    with tempfile.TemporaryDirectory(prefix='mcp HTTP 中文 ') as directory:
        path = Path(directory)
        observations = [await observe(mode, path) for mode in MODES]
        consumption = await consumer(path)
    report = {'observations': observations, 'consumer': consumption, 'python': sys.version,
        'root': str(ROOT), 'module': str(Path(dsh.__file__).resolve())}
    Path(sys.argv[1]).write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
