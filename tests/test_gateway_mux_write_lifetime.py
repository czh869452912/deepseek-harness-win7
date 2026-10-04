import asyncio
from types import SimpleNamespace

import pytest
from wsproto.connection import ConnectionState

from dsh.core.abort import AbortController
from dsh.typert.stream_mux import MuxConnection


class Writer:
    def __init__(self):
        self.closed = False
        self.writes = []

    def is_closing(self):
        return self.closed

    def write(self, value):
        self.writes.append(value)

    async def drain(self):
        pass

    def close(self):
        self.closed = True


def connection(writer, open_stream=None, failure=None):
    mux = MuxConnection({}, writer, open_stream, failure, 30000)
    encodings = []
    def encode(event):
        encodings.append(event)
        return b'controlled encoded frame'
    mux.codec = SimpleNamespace(state=ConnectionState.OPEN, send=encode)
    return mux, encodings


@pytest.mark.asyncio
@pytest.mark.parametrize('physical_closed', [False, True])
async def test_closed_mux_refuses_item_before_mutating_codec_or_writing(physical_closed):
    writer = Writer()
    mux, encodings = connection(writer)
    writer.closed = physical_closed
    mux.closed = not physical_closed
    with pytest.raises(ConnectionError, match='api gateway: Remote stream socket is closed'):
        await mux.send(dict(type='item', streamId='s', value='owned'))
    assert encodings == [] and writer.writes == []


@pytest.mark.asyncio
async def test_queued_mux_write_rechecks_physical_close_after_prior_delivery():
    writer = Writer()
    mux, encodings = connection(writer)
    entered = asyncio.Event()
    await mux.lock.acquire()
    async def deliver():
        entered.set()
        await mux.send(dict(type='item', streamId='s', value='queued'))
    pending = asyncio.create_task(deliver())
    await entered.wait()
    writer.close()
    mux.lock.release()
    with pytest.raises(ConnectionError, match='Remote stream socket is closed'):
        await pending
    assert encodings == [] and writer.writes == []


@pytest.mark.asyncio
async def test_late_stream_item_after_socket_close_drains_without_terminal_or_error_frame():
    writer = Writer()
    entered = asyncio.Event()
    release = asyncio.Event()
    retired = asyncio.Event()
    failures = []
    async def source():
        entered.set()
        try:
            await release.wait()
            yield 'late item'
        finally:
            retired.set()
    async def open_stream(endpoint, payload, signal):
        return source()
    mux, encodings = connection(writer, open_stream, failures.append)
    controller = AbortController()
    pending = asyncio.create_task(mux.pump(dict(streamId='late', endpoint='fixture/read', payload={}), controller))
    mux.streams['late'] = (controller, pending)
    await entered.wait()
    writer.close()
    release.set()
    await pending
    assert retired.is_set() and mux.streams == {}
    assert failures == [] and encodings == [] and writer.writes == []


@pytest.mark.asyncio
async def test_terminate_on_closed_transport_finishes_without_close_frame():
    writer = Writer()
    mux, encodings = connection(writer)
    writer.close()
    await mux.terminate(1011, 'late close')
    assert writer.closed and encodings == [] and writer.writes == []
