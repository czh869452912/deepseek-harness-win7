"""Pair actual multiplexed WebSocket sockets and bounded duplex lifetimes."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


class Client:
    async def connect(self,port,compression=False,auto_pong=True,cookie=None):
        from wsproto import WSConnection,ConnectionType
        from wsproto.events import Request,AcceptConnection
        from wsproto.extensions import PerMessageDeflate
        self.reader,self.writer=await asyncio.open_connection('127.0.0.1',port)
        self.codec,self.events,self.auto_pong,self.pings=WSConnection(ConnectionType.CLIENT),[],auto_pong,0
        self.writer.write(self.codec.send(Request(host='127.0.0.1:'+str(port),target='/api/remote.mux',extensions=[PerMessageDeflate()] if compression else [],extra_headers=[(b'cookie',cookie.encode())] if cookie else [])))
        await self.writer.drain();accepted=await self.event();assert isinstance(accepted,AcceptConnection)
        self.compressed=bool(accepted.extensions)
        self.wire,self.flags=b'',[]
        return self

    async def event(self):
        while not self.events:
            data=await asyncio.wait_for(self.reader.read(65536),2)
            if not data:return None
            if hasattr(self,'wire'):self.record(data)
            self.codec.receive_data(data);self.events.extend(self.codec.events())
        return self.events.pop(0)

    def record(self,data):
        self.wire+=data
        while len(self.wire)>=2:
            length=self.wire[1]&127;offset=2
            if length in (126,127):
                count=2 if length==126 else 8
                if len(self.wire)<2+count:return
                length=int.from_bytes(self.wire[2:2+count],'big');offset+=count
            if self.wire[1]&128:offset+=4
            if len(self.wire)<offset+length:return
            if self.wire[0]&15==1:self.flags.append(bool(self.wire[0]&64))
            self.wire=self.wire[offset+length:]

    async def send(self,value,raw=False,binary=False):
        from wsproto.events import TextMessage,BytesMessage
        text=value if raw else json.dumps(value,ensure_ascii=False,separators=(',',':'))
        self.writer.write(self.codec.send(BytesMessage(data=text.encode()) if binary else TextMessage(data=text)))
        await self.writer.drain()

    async def receive(self):
        from wsproto.events import TextMessage,Ping,CloseConnection
        parts=[]
        while True:
            event=await self.event()
            if event is None:return dict(closed=1006,reason='')
            if isinstance(event,Ping):
                self.pings+=1
                if self.auto_pong:self.writer.write(self.codec.send(event.response()));await self.writer.drain()
            elif isinstance(event,CloseConnection):return dict(closed=int(event.code),reason=event.reason or '')
            elif isinstance(event,TextMessage):
                parts.append(event.data)
                if event.message_finished:return json.loads(''.join(parts))

    async def close(self):
        self.writer.close();await self.writer.wait_closed()


CASES=['echo','queued','overflow','after-end','cancel','unknown','duplicate','invalid','binary','peer-left','failure','cycle','compression','no-negotiation','heartbeat']


async def observe():
    from dsh.cordis import Context
    from dsh.host.webserver.webserver import WebServerService
    from dsh.host.connection.peer import Peer
    from dsh.typert.duplex_mux import DuplexStreamMux
    from dsh.typert.remote import remote_error_of
    from dsh.typert.rpc_result import json_projection
    rows=[]
    for name in CASES:
        ctx=Context();server=WebServerService(ctx,host='127.0.0.1',port=0);peer=Peer(ctx,dict(principal=dict(kind='owner')))
        retired=asyncio.Event();gate=asyncio.Event();windows=[]
        async def opener(endpoint,payload,uplink,trusted,control,window):
            windows.append(dict(endpoint=endpoint,peer=trusted is peer,window=window))
            if name=='queued' and endpoint=='fixture':await gate.wait()
            async def source():
                try:
                    if endpoint=='barrier':yield dict(barrier=True);return
                    yield dict(ready=True)
                    if name in ('overflow','after-end','duplicate','peer-left','heartbeat'):
                        await control.signal.wait_aborted();return
                    if name=='failure':raise RuntimeError('fixture failed')
                    if name=='cycle':
                        value={};value['cycle']=value;yield value;return
                    iterator=uplink.__aiter__()
                    while True:
                        try:value=await iterator.__anext__()
                        except StopAsyncIteration:return
                        yield value
                finally:retired.set()
            return source()
        def failure(error):return remote_error_of(error) or dict(code='fixture/error',message=str(error),details={})
        mux=DuplexStreamMux(opener,failure,heartbeat_ms=20 if name=='heartbeat' else 10000,inbox_bytes=8192 if name in ('compression','no-negotiation') else 200,compression=name in ('compression','no-negotiation'))
        server.register_upgrade('/api/remote.mux',lambda req,writer:mux.upgrade(req,writer,peer));await server.start()
        client=await Client().connect(server.listened_port,compression=name=='compression',auto_pong=name!='heartbeat')
        frames=[]
        async def take():
            value=await client.receive();frames.append(value);return value
        try:
            key='s-中';await client.send(dict(type='open',streamId=key,endpoint='fixture',payload={}))
            if name=='queued':
                await client.send(dict(type='item',streamId=key,value='queued'))
                await client.send(dict(type='end',streamId=key))
                await client.send(dict(type='open',streamId='barrier',endpoint='barrier',payload={}))
                await take();await take();gate.set();await take();await take();await take()
            else:
                await take()
                if name in ('echo','compression','no-negotiation'):
                    await client.send(dict(type='item',streamId=key,value='x'*4096 if name in ('compression','no-negotiation') else '中文'))
                    await take();await client.send(dict(type='item',streamId=key));await take();await client.send(dict(type='end',streamId=key));await take()
                elif name=='overflow':await client.send(dict(type='item',streamId=key,value='x'*201));await take()
                elif name=='after-end':await client.send(dict(type='end',streamId=key));await client.send(dict(type='item',streamId=key,value=1));await take()
                elif name=='cancel':
                    await client.send(dict(type='cancel',streamId=key));await asyncio.wait_for(retired.wait(),2)
                    await client.send(dict(type='open',streamId='barrier',endpoint='barrier',payload={}));await take();await take()
                elif name=='unknown':
                    for kind in ('item','end','cancel'):await client.send(dict(type=kind,streamId='unknown'))
                    await client.send(dict(type='end',streamId=key));await take()
                elif name=='duplicate':await client.send(dict(type='open',streamId=key,endpoint='fixture',payload={}));await take()
                elif name=='invalid':await client.send('{',raw=True);await take()
                elif name=='binary':await client.send('binary',raw=True,binary=True);await take()
                elif name=='peer-left':await peer.dispose();await take()
                elif name in ('failure','cycle','heartbeat'):await take()
            rows.append(dict(name=name,frames=frames,windows=windows,compressed=client.compressed,compressedFrames=client.flags,heartbeatPings=client.pings if name=='heartbeat' else 0))
        finally:
            gate.set();await client.close();await mux.close();await server.stop();await ctx.fiber.dispose()
    return json_projection(rows)


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_duplex_mux.mts','Actual WebSocket mux sockets: duplex JSON/undefined uplink, immediate pre-opener buffering, complete-frame inbox windows, overflow and half-close failures, cancel/unknown frame handling, physical protocol closes, Peer disposal, failure serialization, negotiated compression and missed-Pong heartbeat.',[Path(__file__).resolve(),ROOT/'dsh/typert/duplex_mux.py',ROOT/'dsh/typert/uplink_inbox.py'])
