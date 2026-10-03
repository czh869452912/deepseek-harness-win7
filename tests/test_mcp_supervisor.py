import asyncio
import math
import sys

import pytest

from dsh.cordis.context import Context
from dsh.core.tools import ToolsService
from dsh.mcp.client import McpClientPlugin, _active_server_names
from dsh.mcp.connection import McpConnection, resolve_reconnect_policy
from test_mcp_stdio_transport import SERVER


@pytest.fixture
def server(tmp_path):
    path = tmp_path / 'server.py'
    path.write_text(SERVER, encoding='utf-8')
    return path


class Peer:
    def __init__(self, names=('echo',), failure=None):
        self.names, self.failure = names, failure
        self.on_close = self.on_notification = None
        self.connecting, self.listed, self.release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.block_connect = self.block_list = False
        self.list_calls, self.close_calls = 0, 0
        self.notifications = []

    async def connect(self):
        self.connecting.set()
        if self.block_connect:
            await self.release.wait()
        if self.failure:
            raise self.failure
        return self

    async def request(self, packet, **kwargs):
        if packet['method'] == 'tools/list':
            self.list_calls += 1
            self.listed.set()
            if self.block_list:
                await self.release.wait()
            return {'tools': [{'name': name, 'inputSchema': {'type': 'object'}} for name in self.names]}
        return {'content': [{'type': 'text', 'text': 'actual consumer'}]}

    async def close(self):
        self.close_calls += 1
        self.release.set()
        if self.on_close:
            self.on_close()

    def changed(self):
        task = asyncio.create_task(self.on_notification({'method': 'notifications/tools/list_changed'}))
        self.notifications.append(task)
        return task


def context():
    ctx = Context()
    ctx.set_service('tools', ToolsService(ctx))
    return ctx


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), 2)


@pytest.mark.parametrize('option', ['initialDelayMs', 'maxDelayMs', 'maxAttempts'])
@pytest.mark.parametrize('value', [True, False, math.nan, math.inf, -math.inf, 0, -1, '10'])
def test_reconnect_rejects_non_javascript_numbers(option, value):
    with pytest.raises(ValueError, match=option):
        resolve_reconnect_policy({option: value})


def test_reconnect_accepts_integral_javascript_number_budget():
    assert resolve_reconnect_policy({'maxAttempts': 3.0})['maxAttempts'] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('blocked', ['connect', 'list'])
async def test_dispose_quiesces_connect_or_fetch_and_cannot_publish_late_tools(monkeypatch, blocked):
    peer = Peer()
    peer.block_connect, peer.block_list = blocked == 'connect', blocked == 'list'
    monkeypatch.setattr('dsh.mcp.connection.create_transport', lambda config: peer)
    ctx = context()
    connection = McpConnection(ctx, {'serverName': 'owned'}, resolve_reconnect_policy())
    await asyncio.wait_for((peer.connecting if blocked == 'connect' else peer.listed).wait(), 2)
    await asyncio.wait_for(asyncio.gather(connection.dispose(), connection.dispose()), 2)
    assert connection._start_task.done() and connection.client is None
    assert connection.disposed and connection.disposers == {}
    assert not ctx.get('tools').has_tool('mcp__owned__echo')
    assert peer.close_calls == 1 and connection._retry_task is None


@pytest.mark.asyncio
async def test_serialized_notifications_keep_last_good_fetch_then_swap_and_dispose(monkeypatch):
    peer = Peer()
    monkeypatch.setattr('dsh.mcp.connection.create_transport', lambda config: peer)
    ctx = context()
    connection = McpConnection(ctx, {'serverName': 'owned'}, resolve_reconnect_policy({'enabled': False}))
    assert await connection.ready == {}
    assert 'actual consumer' in await ctx.get('tools').execute_tool('mcp__owned__echo', {})
    peer.names = ('duplicate', 'duplicate')
    await peer.changed()
    assert ctx.get('tools').has_tool('mcp__owned__echo')
    peer.names = ('new',)
    peer.block_list = True
    first, second = peer.changed(), peer.changed()
    await until(lambda: peer.list_calls == 3)
    assert not second.done()
    peer.release.set()
    await asyncio.gather(first, second)
    assert peer.list_calls == 4
    assert not ctx.get('tools').has_tool('mcp__owned__echo')
    assert ctx.get('tools').has_tool('mcp__owned__new')
    await connection.dispose()
    assert not ctx.get('tools').has_tool('mcp__owned__new')


@pytest.mark.asyncio
async def test_retry_budget_is_not_reset_by_brief_success_and_give_up_clears_tools(monkeypatch):
    created = []
    def factory(config):
        peer = Peer()
        created.append(peer)
        return peer
    monkeypatch.setattr('dsh.mcp.connection.create_transport', factory)
    ctx = context()
    connection = McpConnection(ctx, {'serverName': 'owned'}, resolve_reconnect_policy({
        'initialDelayMs': 1, 'maxDelayMs': 1000, 'maxAttempts': 2}))
    await connection.ready
    for count in (2, 3):
        created[-1].on_close()
        created[-1].on_close()
        await until(lambda: len(created) == count and connection._connected_at is not None)
    created[-1].on_close()
    await until(lambda: not connection.disposers)
    assert len(created) == 3 and connection._failed_attempts == 3
    assert not ctx.get('tools').has_tool('mcp__owned__echo')
    await connection.dispose()


@pytest.mark.asyncio
async def test_stable_generation_resets_outage_budget(monkeypatch):
    created = []
    def factory(config):
        peer = Peer()
        created.append(peer)
        return peer
    monkeypatch.setattr('dsh.mcp.connection.create_transport', factory)
    connection = McpConnection(context(), {}, resolve_reconnect_policy({
        'initialDelayMs': 1, 'maxDelayMs': 1000, 'maxAttempts': 1}))
    await connection.ready
    created[0].on_close()
    await until(lambda: len(created) == 2 and connection._connected_at is not None)
    connection._connected_at -= 2
    created[1].on_close()
    await until(lambda: len(created) == 3 and connection._connected_at is not None)
    assert connection._failed_attempts == 1
    await connection.dispose()


@pytest.mark.asyncio
async def test_disabled_reconnect_keeps_owned_tools_until_disposal(monkeypatch):
    peer = Peer()
    monkeypatch.setattr('dsh.mcp.connection.create_transport', lambda config: peer)
    ctx = context()
    connection = McpConnection(ctx, {'serverName': 'owned'}, resolve_reconnect_policy({'enabled': False}))
    await connection.ready
    peer.on_close()
    assert connection.client is None and connection._retry_task is None
    assert ctx.get('tools').has_tool('mcp__owned__echo')
    await connection.dispose()
    assert not ctx.get('tools').has_tool('mcp__owned__echo')


@pytest.mark.asyncio
async def test_failed_generation_without_close_signal_never_overlaps_retry(monkeypatch):
    peer = Peer(failure=RuntimeError('controlled failure'))
    async def broken_close():
        peer.close_calls += 1
    peer.close = broken_close
    created = []
    def factory(config):
        created.append(peer)
        return peer
    monkeypatch.setattr('dsh.mcp.connection.create_transport', factory)
    monkeypatch.setattr('dsh.mcp.connection.GENERATION_CLOSE_TIMEOUT', 0.01)
    connection = McpConnection(context(), {}, resolve_reconnect_policy({'initialDelayMs': 1}))
    assert str((await connection.ready)['error']) == 'controlled failure'
    assert connection._retry_task is None and connection.client is None and len(created) == 1
    await connection.dispose()


@pytest.mark.asyncio
async def test_fatal_startup_registration_failure_is_reported_and_owned_partial_tools_removed(monkeypatch):
    peer = Peer(names=('new', 'collision'))
    monkeypatch.setattr('dsh.mcp.connection.create_transport', lambda config: peer)
    ctx = context()
    foreign = ctx.get('tools').register_legacy({'name': 'mcp__owned__collision', 'parameters': {'type': 'object'},
                                              'handler': lambda **kwargs: 'foreign'})
    connection = McpConnection(ctx, {'serverName': 'owned', 'failOnStartupError': True},
                               resolve_reconnect_policy({'enabled': False}))
    assert isinstance((await connection.ready)['error'], ValueError)
    assert not ctx.get('tools').has_tool('mcp__owned__new')
    await connection.dispose()
    assert ctx.get('tools').has_tool('mcp__owned__collision')
    foreign()


@pytest.mark.asyncio
async def test_service_name_reservation_is_owned_and_released_on_awaited_unload(monkeypatch):
    monkeypatch.setattr('dsh.mcp.connection.create_transport', lambda config: Peer())
    roots = [context(), context()]
    plugins = [McpClientPlugin({'serverName': 'same'}) for root in roots]
    try:
        await asyncio.gather(*(plugin.apply(root) for plugin, root in zip(plugins, roots)))
        with pytest.raises(ValueError, match='already in use'):
            await McpClientPlugin({'serverName': 'same'}).apply(roots[0])
        assert all(root.get('tools').has_tool('mcp__same__echo') for root in roots)
    finally:
        await asyncio.gather(*(root.fiber.dispose() for root in roots))
    assert all(plugin.connection._dispose_task.done() for plugin in plugins)
    assert not any(id(root) in _active_server_names for root in roots)


@pytest.mark.asyncio
async def test_real_stdio_connection_registers_actual_tools_service_consumer(server):
    ctx = context()
    plugin = McpClientPlugin({'serverName': 'real', 'transport': 'stdio', 'command': sys.executable,
                              'args': [str(server)], 'reconnect': {'enabled': False}})
    try:
        fiber = ctx.plugin(plugin)
        await fiber
        assert 'controlled consumer' in await ctx.get('tools').execute_tool('mcp__real__echo', {'text': 'controlled consumer'})
    finally:
        await ctx.fiber.dispose()
    assert plugin.connection.disposed and plugin.connection.disposers == {}
    assert plugin.connection._start_task.done()
