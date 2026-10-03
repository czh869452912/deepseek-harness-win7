import argparse
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

PRODUCT_ROOT = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=PRODUCT_ROOT)
    arguments = parser.parse_args()
    PRODUCT_ROOT = arguments.root.resolve()
sys.path.insert(0, str(PRODUCT_ROOT))
import dsh
import dsh.mcp.connection as supervisor


NAMES = ('connect-resolve', 'connect-reject', 'initial-list', 'resync-list', 'resync-reject', 'queued-resync')


async def observations():
    rows = []
    original_factory = supervisor.create_transport
    try:
        for name in NAMES:
            trace, logs, registered, peers = [], [], set(), []
            entered = asyncio.Event()
            connect_gate, list_gate = asyncio.get_running_loop().create_future(), asyncio.get_running_loop().create_future()
            fetches = 0
            class Peer:
                def __init__(self):
                    self.on_close = self.on_notification = None
                async def connect(self):
                    trace.append(['connect'])
                    if name.startswith('connect-'):
                        entered.set()
                        await connect_gate
                async def close(self):
                    trace.append(['close'])
                    self.on_close()
                async def request(self, packet):
                    nonlocal fetches
                    trace.append(['fetch', packet['method']])
                    fetches += 1
                    if name == 'initial-list' or fetches > 1:
                        entered.set()
                        return await list_gate
                    return {'tools': [{'name': 'old', 'inputSchema': {'type': 'object'}}]}
            def factory(config):
                peer = Peer()
                peers.append(peer)
                trace.append(['create', len(peers)])
                return peer
            supervisor.create_transport = factory
            class Tools:
                def register(self, definition):
                    tool_name = definition['name']
                    trace.append(['register', tool_name])
                    registered.add(tool_name)
                    def dispose():
                        trace.append(['unregister', tool_name])
                        registered.remove(tool_name)
                    return dispose
            tools = Tools()
            ctx = SimpleNamespace(get=lambda key: tools if key == 'tools' else None,
                logger=SimpleNamespace(**{level: lambda message, level=level: logs.append([level, message]) for level in ('warn', 'error', 'info')}))
            handle = supervisor.McpConnection(ctx, {'serverName': 'controlled'},
                {'enabled': False, 'initialDelayMs': 1, 'maxDelayMs': 1000, 'maxAttempts': 1})
            notifications = []
            try:
                if name.startswith('resync-') or name == 'queued-resync':
                    await handle.ready
                    notifications.append(asyncio.create_task(peers[0].on_notification({'method': 'notifications/tools/list_changed'})))
                    if name == 'queued-resync':
                        notifications.append(asyncio.create_task(peers[0].on_notification({'method': 'notifications/tools/list_changed'})))
                await asyncio.wait_for(entered.wait(), 5)
                before = sorted(registered)
                disposing = asyncio.create_task(handle.dispose())
                deadline = asyncio.get_running_loop().time() + 5
                while ['close'] not in trace:
                    assert asyncio.get_running_loop().time() < deadline
                    await asyncio.sleep(0)
                if name == 'connect-reject':
                    connect_gate.set_exception(RuntimeError('controlled disposed connect'))
                else:
                    connect_gate.set_result(None)
                if name == 'resync-reject':
                    list_gate.set_exception(RuntimeError('controlled disposed fetch'))
                else:
                    list_gate.set_result({'tools': [{'name': 'late', 'inputSchema': {'type': 'object'}}]})
                await disposing
                await asyncio.gather(*notifications)
                outcome = await handle.ready
                rows.append({'name': name, 'before': before, 'after': sorted(registered), 'outcome': {
                    key: {'name': getattr(error, 'name', 'Error'), 'message': str(error)} for key, error in outcome.items()},
                    'trace': trace, 'logs': logs})
            finally:
                await handle.dispose()
        return rows
    finally:
        supervisor.create_transport = original_factory


async def factory_observation():
    attempted, logs = asyncio.Event(), []
    original = supervisor.create_transport
    def factory(config):
        attempted.set()
        return original(config)
    supervisor.create_transport = factory
    ctx = SimpleNamespace(get=lambda key: None,
        logger=SimpleNamespace(**{level: lambda message, level=level: logs.append([level, message]) for level in ('warn', 'error', 'info')}))
    handle = supervisor.McpConnection(ctx, {'transport': 'streamable-http', 'serverName': 'controlled',
        'url': 'invalid', 'headers': {}}, {'enabled': True, 'initialDelayMs': 1, 'maxDelayMs': 1000, 'maxAttempts': 1})
    try:
        await attempted.wait()
        await handle.dispose()
        error = (await handle.ready)['error']
        return {'outcome': {'name': error.name, 'message': str(error), 'code': error.code}, 'logs': logs}
    finally:
        await handle.dispose()
        supervisor.create_transport = original


async def main():
    return {'supervisor': await observations(), 'factory': await factory_observation(),
        'root': str(PRODUCT_ROOT), 'module': str(Path(dsh.__file__).resolve()), 'python': list(sys.version_info[:3])}


if __name__ == '__main__':
    arguments.output.write_text(json.dumps(asyncio.run(main()), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
