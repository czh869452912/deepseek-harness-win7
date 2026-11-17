"""Actual plain/TLS upgrade ownership after the route callback returns."""
import asyncio
import json
from pathlib import Path
import ssl
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def scenario(secure, peer_end=False):
    from dsh.cordis import Context
    from dsh.host.webserver.current import CurrentWebServer
    ctx=Context();jobs=set();writers=[];calls=[];eof=asyncio.Event();release=asyncio.Event()
    config=dict(certFile=str(ROOT/'tests/fixtures/tls/localhost-cert.pem'),keyFile=str(ROOT/'tests/fixtures/tls/localhost-key.pem'))
    server=CurrentWebServer(ctx,port=0,tls=config if secure else None)
    def upgrade(request,writer):
        calls.append('handler-returned')
        writer.write(b'HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n')
        async def echo():
            try:
                while True:
                    data=await request['reader'].read(5)
                    if not data:
                        eof.set()
                        await release.wait()
                        break
                    writer.write(b'ACK:'+data);await writer.drain()
            finally:
                writer.close()
                try:await writer.wait_closed()
                except (ConnectionError,OSError):pass
        job=asyncio.create_task(echo());jobs.add(job)
        job.add_done_callback(lambda done:None if done.cancelled() else done.exception())
    server.register_upgrade('/owned',upgrade)
    context=ssl.create_default_context(cafile=config['certFile']) if secure else None
    try:
        await server.start()
        reader,writer=await asyncio.open_connection('127.0.0.1',server.port,ssl=context)
        writers.append(writer)
        writer.write(b'GET /owned HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: test\r\n\r\n');await writer.drain()
        header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),2)
        await asyncio.sleep(.02)
        replies=[]
        for data in (b'hello',b'world'):
            writer.write(data);await writer.drain()
            replies.append((await asyncio.wait_for(reader.readexactly(9),2)).decode('ascii'))
        half_open=None
        if peer_end:
            writer.write_eof()
            await asyncio.wait_for(eof.wait(),2)
            half_open=not next(iter(server._upgraded_sockets)).is_closing()
        await asyncio.wait_for(server.stop(),2)
        release.set()
        ended=await asyncio.wait_for(reader.read(),2)==b''
        await asyncio.wait_for(asyncio.gather(*jobs),2)
        await asyncio.sleep(0)
        return dict(secure=secure,peerEnd=peer_end,status=int(header.split(b' ')[1]),calls=calls,replies=replies,
            halfOpen=half_open,closed=ended,ownerJobsSettled=all(job.done() for job in jobs),trackedSockets=len(server._upgraded_sockets))
    finally:
        release.set()
        await server.stop()
        for writer in writers:
            writer.close()
            try:await writer.wait_closed()
            except (ConnectionError,OSError):pass
        await asyncio.gather(*jobs,return_exceptions=True)
        await ctx.fiber.dispose()


async def observe():return [await scenario(secure,peer_end) for secure,peer_end in ((False,False),(True,False),(False,True))]


def prepare(output):
    path=output/'tls.json';path.write_text(json.dumps(dict(cert=str(ROOT/'tests/fixtures/tls/localhost-cert.pem'),key=str(ROOT/'tests/fixtures/tls/localhost-key.pem'))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_upgrade_owner.mts',scope='Actual original plain/TLS upgrade callbacks return immediately while the transferred socket answers two later frames; service unload closes it and owner read jobs settle.',
        prepare=prepare,extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/host/webserver/webserver.py',ROOT/'dsh/host/webserver/current.py',ROOT/'dsh/host/webserver/socket_server.py'])
