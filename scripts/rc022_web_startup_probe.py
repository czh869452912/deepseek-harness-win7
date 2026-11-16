"""Pair actual original/current CLI providers including rejection output."""
import asyncio
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    return [[],['--no-open'],['--host','127.0.0.1','--port','0'],
        ['--host','::1','--public-url','HTTPS://APP.EXAMPLE/ui','--trusted-host','a','b','--trusted-host','c','--tls-cert','chain.pem','--tls-key','key.pem'],
        ['--tls-cert','chain.pem'],['--tls-key','key.pem'],['--host','0.0.0.0'],['--host','::'],
        ['--host','0:0:0:0:0:0:0:0'],['--host','localhost'],['--port','no'],['--port','-1'],
        ['--port','65536'],['--public-url','https:///ui'],['--public-url','https://host/?'],
        ['--public-url','https://user@host/'],['--tls-cert','x','--public-url','bad'],['--unknown'],['--port'],['--help']]


async def observe():
    from dsh.cordis import Context
    from dsh.boot.cmdline import provide_cmdline,internals
    from dsh.bundle.web_app.startup_current import CurrentWebStartup
    stdout,stderr=internals.stdout,internals.stderr;rows=[]
    class Stream:
        def __init__(self):self.chunks=[]
        def write(self,value):self.chunks.append(value);return True
    try:
        for args in corpus():
            ctx=Context();exits=[];stream=Stream();internals.stdout=stream;internals.stderr=stream
            try:
                provide_cmdline(ctx,dict(args=args,exit=exits.append))
                await ctx.plugin(CurrentWebStartup);await asyncio.sleep(0)
                value=ctx.get('webStartup')
                rows.append(dict(args=args,values=value.to_dict() if value is not None else None,exits=exits,out=''.join(stream.chunks)))
            finally:await ctx.fiber.dispose()
    finally:internals.stdout=stdout;internals.stderr=stderr
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_web_startup.mts','Actual current CLI providers: published and absent fields, TLS pairing, public URL validation/rejection precedence, wildcard address errors, unknown/missing flags and full help output.',[Path(__file__).resolve(),ROOT/'dsh/bundle/web_app/startup_current.py'],prepare=prepare)
