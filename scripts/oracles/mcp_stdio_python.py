import asyncio
import argparse
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]


MODES = ['normal', 'notification', 'out-of-order', 'peer-error', 'peer-error-null',
         'cancel', 'timeout', 'eof', 'unsupported', 'capabilities-empty', 'missing-executable']


async def observe(mode, directory, peer_script):
    from dsh.core.abort import AbortController
    from dsh.mcp.stdio_client import McpError
    from dsh.mcp.transport import StdioMcpTransport
    records = directory / (mode + '.json')
    executable = str(directory / 'missing-executable.exe') if mode == 'missing-executable' else sys.executable
    client = StdioMcpTransport(executable, [str(peer_script), mode, str(records)])
    notifications = []
    client.on_notification = notifications.append
    observed = {'mode': mode, 'notifications': notifications}
    try:
        await client.connect()
        observed['server'] = client.server_info
        observed['tools'] = await client.request({'method': 'tools/list'})
        def call(text='中文😀', **options):
            return client.request({'method': 'tools/call', 'params': {'name': 'echo', 'arguments': {'text': text}}}, **options)
        if mode == 'out-of-order':
            observed['results'] = await asyncio.gather(*(call(str(index)) for index in range(3)))
        elif mode == 'cancel':
            controller = AbortController()
            pending = asyncio.create_task(call(signal=controller.signal))
            async def admitted():
                while not Path(str(records) + '.admitted').exists():
                    await asyncio.sleep(0.005)
            await asyncio.wait_for(admitted(), 2)
            controller.abort('controlled cancel')
            observed['results'] = [await pending]
        else:
            observed['results'] = [await call(timeout=20 if mode == 'timeout' else 60000)]
    except Exception as error:
        observed['error'] = {'message': str(error)}
        if isinstance(error, McpError):
            observed['error']['code'] = error.code
            if error.has_data:
                observed['error']['data'] = error.data
    finally:
        await client.close()
    observed['frames'] = json.loads(records.read_text(encoding='utf-8')) if records.exists() else []
    observed['closed'] = client.proc is None or client.proc.returncode is not None
    observed['reaped'] = client.proc is None or client.proc.returncode is not None
    return observed


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--peer-script', type=Path, default=ROOT / 'scripts/oracles/mcp_stdio_peer.py')
    parser.add_argument('--consumer', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    import dsh
    if Path(dsh.__file__).resolve().parent != root / 'dsh':
        raise RuntimeError('MCP observer imported a different product root')
    with tempfile.TemporaryDirectory(prefix='mcp-native-observer-') as directory:
        observations = [await observe(mode, Path(directory), args.peer_script.resolve()) for mode in MODES]
        result = observations
        if args.consumer:
            from dsh.cordis.context import Context
            from dsh.core.tools import ToolsService
            from dsh.mcp.client import McpClientPlugin
            ctx = Context()
            tools = ToolsService(ctx)
            ctx.set_service('tools', tools)
            plugin = McpClientPlugin({'serverName': 'portable', 'transport': 'stdio', 'command': sys.executable,
                'args': [str(args.peer_script.resolve()), 'normal', str(Path(directory) / 'consumer.json')],
                'reconnect': {'enabled': False}})
            try:
                fiber = ctx.plugin(plugin)
                await fiber
                consumer = {'registered': tools.has_tool('mcp__portable__echo'),
                            'output': await tools.execute_tool('mcp__portable__echo', {'text': 'controlled consumer'})}
                child = plugin.connection.client.proc
            finally:
                await ctx.fiber.dispose()
            consumer.update(retired=not tools.has_tool('mcp__portable__echo'),
                            childExited=child.returncode is not None, pending=len(plugin.connection.disposers))
            result = {'observations': observations, 'consumer': consumer,
                      'python': sys.version, 'root': str(root), 'module': str(Path(dsh.__file__).resolve())}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
