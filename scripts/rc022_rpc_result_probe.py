"""Pair actual Gateway RPC materialization and result-relative byte paths."""
import datetime
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
CASES=['plain','root-bytes','nested-bytes','empty-bytes','shared','undefined','function','json-omissions','cycle','to-json-bytes','getter','date','strict-encode','strict-absent-encode','strict-nullish-fallback','numeric-keys']


def fixture(name, calls):
    from dsh.core.session.json import UNDEFINED
    shared=dict(data=b'abc')
    if name=='plain':return dict(text='中文',number=2,empty=None)
    if name=='root-bytes':return b'abc'
    if name=='nested-bytes':return {'a.b/c':[memoryview(b'01234')[1:4],dict(data=b'xy')],'__proto__':dict(data=b'z')}
    if name=='empty-bytes':return dict(data=b'')
    if name=='numeric-keys':return {'10':b'ten','2':b'two','x':b'x'}
    if name=='shared':return dict(a=shared,b=shared)
    if name=='undefined':return UNDEFINED
    if name=='function':return lambda:None
    if name=='json-omissions':return dict(missing=UNDEFINED,fn=lambda:None,array=[UNDEFINED,lambda:None,float('nan'),float('inf')])
    if name=='cycle':
        value={};value['cycle']=value;return value
    if name=='to-json-bytes':
        def to_json(key):calls.append(key);return dict(data=b'json')
        return dict(nested=dict(toJSON=to_json))
    if name=='getter':
        class Getter(dict):
            def __getitem__(self,key):
                calls.append(key);return super().__getitem__(key)
        return Getter(data=b'getter')
    if name=='date':return datetime.datetime(2026,1,2,3,4,5,6000,tzinfo=datetime.timezone.utc)
    return dict(raw=b'strict')


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.host.connection.peer import Peer
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_core import AuthorizedGatewayCore
    from dsh.typert.remote import Remote,TypertRemoteService
    from dsh.typert.rpc_result import json_projection
    rows=[]
    for name in CASES:
        ctx=Context();await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService);await ctx.plugin(AuthorizedGatewayCore)
        calls=[]
        class Fixture(TypertRemoteService):
            def __init__(self,child):super().__init__(child,'fixture')
            @Remote
            def value(self):return fixture(name,calls)
        try:
            await ctx.plugin(Fixture)
            if name.startswith('strict'):
                codec=dict(mode='strict',typeSymbol='Result')
                from dsh.typert.artifact import Schema
                codec['schema']=Schema('unknown')
                if name!='strict-absent-encode':
                    def encode(value, write):
                        projected=dict(data=write(value['raw'],['data']))
                        return None if name=='strict-nullish-fallback' else projected
                    codec['encode']=encode
                row=dict(id='fixture#value',service='fixture',namespace='fixture',method='value',parameters=[],invocation=dict(kind='direct'),result=codec)
                ctx.typert.register(dict(package='fixture',face='host',model={},schemas=[],invocations=[row]))
            peer=Peer(ctx,dict(principal=dict(kind='owner')))
            result=await ctx.typertGateway.invoke_rpc('fixture/value',dict(args={}),NEVER_ABORTED,peer)
            if 'attachments'in result:result=dict(result,attachments=[dict(path=item['path'],bytes=list(bytes(item['bytes']))) for item in result['attachments']])
            rows.append(dict(name=name,result=json_projection(result),calls=calls))
        finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_rpc_result.mts','Actual Gateway RPC result materialization, byte view offsets and attachment paths, one-time toJSON/getter access, dates/shared/cyclic results, absent/JSON-omitted values and strict codec encoders/nullish fallback. HTTP multipart carrier remains separate.',
        [Path(__file__).resolve(),ROOT/'dsh/typert/rpc_result.py',ROOT/'dsh/typert/gateway_core.py'])
