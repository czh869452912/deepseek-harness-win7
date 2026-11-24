import pytest
import asyncio
from types import SimpleNamespace
from wsproto.connection import ConnectionState
from wsproto.events import CloseConnection
from wsproto.frame_protocol import Opcode, RsvBits
from dsh.typert.duplex_mux import DuplexConnection, _ThresholdDeflate, _large_text
from scripts.rc022_duplex_mux_probe import observe


@pytest.mark.asyncio
async def test_actual_duplex_sockets_and_physical_lifetimes():
    rows={row['name']:row for row in await observe()}
    assert len(rows)==15
    assert rows['echo']['frames'][2]==dict(type='item',streamId='s-中')
    assert rows['queued']['frames'][-2]['value']=='queued'
    assert rows['overflow']['frames'][-1]['error']['code']=='gateway/uplink-overflow'
    assert rows['after-end']['frames'][-1]['error']['code']=='gateway/protocol'
    assert rows['cancel']['frames'][1]['streamId']=='barrier'
    assert rows['duplicate']['frames'][-1]['closed']==1008
    assert rows['binary']['frames'][-1]['closed']==1003
    assert rows['peer-left']['frames'][-1]==dict(closed=1001,reason='peer left')
    assert rows['compression']['compressed'] is True
    assert rows['compression']['frames'][1]['value']=='x'*4096
    assert rows['compression']['compressedFrames']==[False,True,False,False]
    assert rows['no-negotiation']['compressedFrames']==[False,False,False,False]
    assert rows['heartbeat']['heartbeatPings']==2


class Writer:
    def __init__(self):self.closed=False;self.writes=[]
    def is_closing(self):return self.closed
    def write(self,value):self.writes.append(value)
    async def drain(self):pass
    def close(self):self.closed=True


@pytest.mark.parametrize(('text', 'compress'), [
    ('a' * 1023, False),
    ('a' * 1024, True),
    ('文' * 1023, False),
    ('文' * 1024, True),
    ('😀' * 511 + 'a', False),
    ('😀' * 512, True),
])
def test_compression_boundary_counts_utf16_units(text, compress):
    deflate = _ThresholdDeflate()
    rsv, _ = deflate.frame_outbound(SimpleNamespace(client=False), Opcode.TEXT,
        RsvBits(False, False, False), text.encode('utf-8'), True)

    assert rsv.rsv1 is compress
    assert _large_text(text) is compress


def connection(failure=lambda error:dict(code='test',message=str(error),details={})):
    writer=Writer();owner=SimpleNamespace(compression=True,failure=failure)
    mux=DuplexConnection(owner,{},writer,None);encoded=[]
    def encode(event):encoded.append(event);return b'frame'
    mux.codec=SimpleNamespace(state=ConnectionState.OPEN,send=encode)
    return mux,writer,encoded


@pytest.mark.asyncio
async def test_queued_write_refuses_closed_transport_before_mutating_codec():
    mux,writer,encoded=connection();await mux.lock.acquire()
    pending=asyncio.create_task(mux.send(dict(type='item',streamId='s',value='queued')))
    await asyncio.sleep(0);writer.close();mux.lock.release()
    with pytest.raises(ConnectionError,match='Remote stream socket is closed'):await pending
    assert encoded==[] and writer.writes==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('negotiated',[False,True])
async def test_large_unnegotiated_write_does_not_reset_heartbeat(negotiated):
    mux,writer,encoded=connection();mux.missed=2
    mux.deflate=SimpleNamespace(enabled=lambda:negotiated)
    await mux.send(dict(type='item',streamId='s',value='x'*4096))
    assert mux.missed==(0 if negotiated else 2)
    assert len(encoded)==1


@pytest.mark.asyncio
async def test_unserializable_terminal_failure_closes_physical_generation():
    value={};value['cycle']=value
    mux,writer,encoded=connection(lambda _:value)
    await mux.send_failure('s',RuntimeError('original'))
    assert writer.closed
    assert len(encoded)==1 and isinstance(encoded[0],CloseConnection)
    assert encoded[0].code==1011
    assert encoded[0].reason=='Remote stream failure could not be delivered'
