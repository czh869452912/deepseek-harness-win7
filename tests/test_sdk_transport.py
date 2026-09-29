import asyncio
import io
import json
import os
import pytest

from dsh.core.abort import AbortController
from dsh.sdk.stdio import StdioInput
from dsh.sdk.transport import JsonRpcLineTransport, JsonRpcResponseError


class Input:
    def __init__(self):
        self.listeners = {}

    def on(self, name, fn):
        self.listeners.setdefault(name, []).append(fn)

    def off(self, name, fn):
        self.listeners[name] = [item for item in self.listeners.get(name, []) if item != fn]

    def emit(self, name, *args):
        for fn in list(self.listeners.get(name, [])):
            fn(*args)


async def settled(transport):
    await asyncio.gather(*list(transport.tasks))


@pytest.mark.asyncio
async def test_jsonrpc_utf8_framing_errors_notifications_and_detach():
    incoming, output = Input(), io.StringIO()
    transport = JsonRpcLineTransport(incoming, output)
    transport.start()
    transport.start()
    seen = []
    transport.on_notification(lambda name, params: seen.append((name, params)))
    async def request(name, params):
        if name == 'fail':
            raise ValueError('fixture failure')
        return params
    transport.on_request(request)
    wire = ('broken\n[]\n' + json.dumps(dict(id=1, method='echo', params={'text': '中文'}), ensure_ascii=False) + '\n'
            + json.dumps(dict(id=2, method='fail')) + '\n' + json.dumps(dict(method='notice', params=[1])) + '\n').encode('utf-8')
    for byte in wire:
        incoming.emit('data', bytes([byte]))
    await settled(transport)
    frames = [json.loads(line) for line in output.getvalue().splitlines()]
    assert frames == [dict(jsonrpc='2.0', id=1, result={'text': '中文'}),
                      dict(jsonrpc='2.0', id=2, error=dict(code=-32603, message='fixture failure'))]
    assert seen == [('notice', {})]
    incoming.emit('data', '{"id":3,"method":"echo"}')
    incoming.emit('end')
    await settled(transport)
    assert len(output.getvalue().splitlines()) == 2
    transport.close()
    assert not any(incoming.listeners.values())


@pytest.mark.asyncio
async def test_outbound_response_error_abort_eof_and_no_retained_waiters():
    incoming, output = Input(), io.StringIO()
    transport = JsonRpcLineTransport(incoming, output)
    transport.start()
    task = asyncio.create_task(transport.request('remote', {}))
    await asyncio.sleep(0)
    identity = json.loads(output.getvalue())['id']
    incoming.emit('data', json.dumps(dict(id=identity, error=dict(code=42, message='bad', data={'why': 1}))) + '\n')
    with pytest.raises(JsonRpcResponseError) as caught:
        await task
    assert caught.value.code == 42 and caught.value.data == {'why': 1}
    controller = AbortController()
    task = asyncio.create_task(transport.request('remote', {}, controller.signal))
    await asyncio.sleep(0)
    controller.abort('stop')
    with pytest.raises(RuntimeError, match='aborted'):
        await task
    task = asyncio.create_task(transport.request('remote', {}))
    await asyncio.sleep(0)
    incoming.emit('end')
    with pytest.raises(RuntimeError, match='input closed'):
        await task
    assert not transport.pending
    transport.close()


@pytest.mark.asyncio
async def test_real_pipe_reader_can_unload_while_writer_stays_open():
    read_fd, write_fd = os.pipe()
    source = os.fdopen(read_fd, 'rb', buffering=0)
    reader = StdioInput(source)
    seen, received = [], asyncio.Event()
    reader.on('data', lambda data: (seen.append(data), received.set()))
    try:
        os.write(write_fd, b'hello\n')
        await asyncio.wait_for(received.wait(), 2)
        assert b''.join(seen) == b'hello\n'
        await asyncio.wait_for(reader.close(), 1)
        assert not source.closed and not reader.listeners
        assert reader.task.done()
    finally:
        await reader.close()
        source.close()
        os.close(write_fd)


@pytest.mark.asyncio
async def test_real_pipe_eof_emits_one_end_and_keeps_stream_caller_owned():
    read_fd, write_fd = os.pipe()
    source = os.fdopen(read_fd, 'rb', buffering=0)
    reader = StdioInput(source)
    end = asyncio.Event()
    reader.on('end', end.set)
    reader.on('data', lambda data: None)
    os.close(write_fd)
    try:
        await asyncio.wait_for(end.wait(), 2)
        assert reader.readableEnded
        await reader.close()
        assert not source.closed
    finally:
        source.close()


@pytest.mark.asyncio
async def test_sdk_plugin_shutdown_reply_precedes_disposal_and_exit():
    from test_sdk_server import setup
    from dsh.sdk.plugin import SdkJsonRpcPlugin
    ctx, _, previous = await setup()
    await previous.shutdown()
    incoming = Input()
    class Output(io.StringIO):
        def flush(self):
            order.append('flush')
    order = []
    output = Output()
    exited = asyncio.Event()
    ctx.effect(lambda: lambda: order.append('disposed'))
    def exit_fn(code):
        assert json.loads(output.getvalue().splitlines()[-1]) == dict(jsonrpc='2.0', id=9, result={})
        order.append('exit')
        exited.set()
    await ctx.plugin(SdkJsonRpcPlugin, dict(input=incoming, output=output, exit=exit_fn))
    incoming.emit('data', '{"id":9,"method":"shutdown"}\n')
    await asyncio.wait_for(exited.wait(), 2)
    assert order.index('flush') < order.index('disposed') < order.index('exit')
    assert not any(incoming.listeners.values())
