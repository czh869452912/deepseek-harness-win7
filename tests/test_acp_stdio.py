import asyncio
import io
import json
import threading

import pytest

from dsh.acp.rpc import AcpRpc, RequestError
from dsh.acp.stdio import StdioWriter
from dsh.core.abort import AbortController, AbortError
from test_acp_session_controls import bridge_fixture, dispose_context


class Input:
    readableEnded = False

    def __init__(self):
        self.listeners = {}

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    def off(self, event, callback):
        self.listeners[event].remove(callback)

    def emit(self, event, *args):
        for callback in list(self.listeners.get(event, [])):
            callback(*args)


async def until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(wait(), 3)


@pytest.mark.asyncio
async def test_schema_errors_precede_domain_side_effects_and_provider_value_errors_stay_internal(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    stdin, output = Input(), []
    bridge.config['stream'] = {'input': stdin, 'output': lambda frame: output.append(json.loads(frame))}
    bridge.apply(ctx)
    try:
        stdin.emit('data', '{"jsonrpc":"2.0","id":1,"method":"session/new","params":{"cwd":"C:/work"}}\n')
        await until(lambda: len(output) == 1)
        assert output[0] == {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32602, 'message': 'Invalid params',
            'data': {'_errors': [], 'mcpServers': {'_errors': ['Required value is missing']}}}}
        assert not factory.created and not persistence.headers
        stdin.emit('data', '{"jsonrpc":"2.0","id":2,"method":"session/new","params":{"cwd":"relative","mcpServers":[]}}\n')
        await until(lambda: len(output) == 2)
        assert output[1]['error'] == {'code': -32602, 'message': 'Invalid params: cwd must be an absolute path: relative'}
        assert not factory.created
        async def failed(*args, **kwargs):
            raise ValueError('provider fixture failure')
        factory.create = failed
        stdin.emit('data', json.dumps({'jsonrpc': '2.0', 'id': 3, 'method': 'session/new',
            'params': {'cwd': str(tmp_path), 'mcpServers': []}}) + '\n')
        await until(lambda: len(output) == 3)
        assert output[2]['error'] == {'code': -32603, 'message': 'Internal error', 'data': {'details': 'provider fixture failure'}}
    finally:
        await dispose_context(ctx)
    assert not any(stdin.listeners.values())


@pytest.mark.asyncio
async def test_connection_eof_and_unload_remove_listeners_quiesce_owners_and_refuse_late_requests(tmp_path):
    ctx, bridge, persistence, factory = bridge_fixture()
    stdin, output = Input(), []
    bridge.config['stream'] = {'input': stdin, 'output': lambda frame: output.append(json.loads(frame))}
    bridge.apply(ctx)
    created = await bridge.new_session(ctx, {'cwd': str(tmp_path)})
    try:
        stdin.emit('end')
        await until(lambda: bridge.closed)
        await bridge.close(ctx)
        assert factory.cancelled == factory.created == factory.disposed
        assert factory.flushed == factory.created and not factory.live
        assert not any(stdin.listeners.values())
        stdin.emit('data', '{"jsonrpc":"2.0","id":9,"method":"session/list","params":{}}\n')
        await asyncio.sleep(0)
        assert output == []
        assert created['sessionId'] in persistence.headers
    finally:
        await dispose_context(ctx)


@pytest.mark.asyncio
async def test_request_cancellation_is_typed_and_old_finisher_cannot_remove_replacement():
    output, active = [], []
    connection = AcpRpc(lambda frame: output.append(json.loads(frame)))
    async def wait(params, signal):
        future = asyncio.get_running_loop().create_future()
        detach = signal.add_listener('abort', lambda reason: future.set_exception(reason) if not future.done() else None)
        active.append((signal, future))
        try:
            return await future
        finally:
            detach()
    connection.handlers['wait'] = wait
    try:
        connection.data('{"jsonrpc":"2.0","id":1,"method":"wait"}\n')
        await until(lambda: len(active) == 1)
        connection.data('{"jsonrpc":"2.0","id":1,"method":"wait"}\n')
        await until(lambda: len(active) == 2)
        active[0][1].set_result('first completed')
        await until(lambda: len(output) == 1)
        connection.data('{"jsonrpc":"2.0","method":"$/cancel_request","params":{"requestId":"1"}}\n')
        await asyncio.sleep(.01)
        assert not active[1][0].aborted
        connection.data('{"jsonrpc":"2.0","method":"$/cancel_request","params":{"requestId":1}}\n')
        await until(lambda: len(output) == 2)
        assert output[0] == {'jsonrpc': '2.0', 'id': 1, 'result': 'first completed'}
        assert output[1] == {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32800,
            'message': 'Request cancelled', 'data': {'requestId': 1}}}
    finally:
        connection.close()
        await connection.drain()


@pytest.mark.asyncio
async def test_outgoing_cancellation_waits_for_peer_and_disposes_signal_listener():
    output = []
    connection = AcpRpc(lambda frame: output.append(json.loads(frame)))
    controller = AbortController()
    pending = connection.request('fixture', {'value': False}, controller.signal)
    try:
        await until(lambda: len(output) == 1)
        controller.abort('caller cancellation')
        await until(lambda: len(output) == 2)
        assert not pending.done()
        assert output == [{'jsonrpc': '2.0', 'id': 0, 'method': 'fixture', 'params': {'value': False}},
                          {'jsonrpc': '2.0', 'method': '$/cancel_request', 'params': {'requestId': 0}}]
        connection.data('{"jsonrpc":"2.0","id":0,"result":{"settled":true}}\n')
        assert await asyncio.wait_for(pending, 3) == {'settled': True}
        assert not controller.signal._listeners and not connection.pending
    finally:
        connection.close()
        await connection.drain()


@pytest.mark.asyncio
async def test_aborted_request_throwing_abort_error_uses_exact_cancel_envelope():
    output, entered = [], asyncio.Event()
    connection = AcpRpc(lambda frame: output.append(json.loads(frame)))
    async def wait(params, signal):
        entered.set()
        await signal.wait_aborted()
        raise AbortError()
    connection.handlers['wait'] = wait
    try:
        connection.data('{"jsonrpc":"2.0","id":"call","method":"wait"}\n')
        await entered.wait()
        connection.data('{"jsonrpc":"2.0","method":"$/cancel_request","params":{"requestId":"call"}}\n')
        await until(lambda: output)
        assert output[0]['error'] == {'code': -32800, 'message': 'Request cancelled', 'data': {'requestId': 'call'}}
    finally:
        connection.close()
        await connection.drain()


@pytest.mark.asyncio
async def test_blocked_stdout_does_not_block_event_loop_close_or_start_queued_writes():
    entered, release = threading.Event(), threading.Event()
    class Output(io.StringIO):
        def write(self, content):
            entered.set()
            release.wait(3)
            return super().write(content)
    output = Output()
    writer = StdioWriter(output)
    first = asyncio.create_task(writer.write('first\n'))
    second = None
    try:
        await until(entered.is_set)
        second = asyncio.create_task(writer.write('second\n'))
        await asyncio.sleep(0)
        writer.close()
        for pending in (first, second):
            with pytest.raises(RuntimeError, match='output closed'):
                await asyncio.wait_for(pending, .5)
        release.set()
        await asyncio.get_running_loop().run_in_executor(None, writer.thread.join, 1)
        assert not writer.thread.is_alive()
        assert output.getvalue() == 'first\n' and not output.closed
    finally:
        writer.close()
        release.set()
        await asyncio.gather(*[pending for pending in (first, second) if pending is not None], return_exceptions=True)
