"""Pair actual Gateway core duplex invocations, cancellation and teardown."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

CASES=['duplex','strict-good','strict-bad','peer-cancel','carrier-cancel','early-close','once','unread','invalid-result','wrong-unary','wrong-stream','undefined-uplink','empty-uplink']


class Input:
    def __init__(self, values, hold=False):
        self.values,self.hold,self.returned,self.waiters=list(values),hold,False,[]
    def __aiter__(self):return self
    async def __anext__(self):
        if self.returned:raise StopAsyncIteration
        if self.values:return self.values.pop(0)
        if not self.hold:raise StopAsyncIteration
        future=asyncio.get_running_loop().create_future();self.waiters.append(future)
        try:
            await future
            raise StopAsyncIteration
        finally:self.waiters.remove(future)
    async def aclose(self):
        self.returned=True
        for future in list(self.waiters):
            if not future.done():future.set_result(None)


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    from dsh.host.connection.peer import Peer
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_core import AuthorizedGatewayCore
    from dsh.typert.remote import Remote,TypertRemoteService
    from dsh.typert.artifact import Schema
    rows=[]
    for name in CASES:
        ctx=Context();await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService);await ctx.plugin(AuthorizedGatewayCore)
        carrier=AbortController();peer=Peer(ctx,dict(principal=dict(kind='owner')));closed=[]
        class Fixture(TypertRemoteService):
            def __init__(self, child):super().__init__(child,'fixture')
            @Remote(dict(mode='stream'))
            async def duplex(self, signal):
                try:
                    async for value in self.ctx.invocation.uplink():
                        yield dict(echo='undefined' if value is UNDEFINED else value,signal=signal is self.ctx.invocation.signal)
                finally:closed.append(True)
            @Remote
            async def once(self, signal):
                values=[value async for value in self.ctx.invocation.uplink()]
                try:self.ctx.invocation.uplink()
                except Exception as error:return dict(values=values,error=str(error),sameSignal=signal is carrier.signal,window=self.ctx.invocation.uplinkWindow)
            @Remote
            def unread(self):return 'unread'
            @Remote(dict(mode='stream'))
            def invalid(self):return {}
        try:
            await ctx.plugin(Fixture)
            strict=name.startswith('strict')
            if strict:
                descriptor=dict(id='fixture#duplex',service='fixture',namespace='fixture',method='duplex',mode='stream',parameters=[],cancellation=dict(parameter='signal'),invocation=dict(kind='direct'),result=dict(mode='src-json'),uplink=dict(codec=dict(mode='strict',typeSymbol='Number',schema=Schema('number'))))
                ctx.typert.register(dict(package='fixture',face='host',model={},schemas=[],invocations=[descriptor]))
            method='once' if name in ['once','wrong-stream'] else 'unread' if name=='unread' else 'invalid' if name=='invalid-result' else 'duplex'
            values=[7] if name=='strict-good' else ['bad'] if name=='strict-bad' else [UNDEFINED] if name=='undefined-uplink' else ['a',dict(n=1)]
            source=Input(values,name in ['peer-cancel','carrier-cancel','early-close'])
            request=dict(namespace='fixture',method=method,args={},peer=peer,signal=carrier.signal,uplinkWindow=3)
            if name!='empty-uplink':request['uplink']=source
            result={};stream=None
            try:
                if name in ['once','unread','wrong-unary']:
                    result['value']=await ctx.typertGateway.invoke(request)
                else:
                    stream=await ctx.typertGateway.stream(request)
                    output=[]
                    if name in ['peer-cancel','carrier-cancel','early-close']:
                        output.append(await stream.__anext__())
                        if name=='peer-cancel':await peer.dispose()
                        elif name=='carrier-cancel':carrier.abort(RuntimeError('cancel'))
                        else:await stream.aclose()
                    if name!='early-close':
                        try:
                            async for value in stream:output.append(value)
                        except Exception as error:result['error']=dict(code=error.code,details=error.details)
                    result['output']=output
            except Exception as error:result['error']=dict(code=error.code,details=error.details)
            finally:
                if stream is not None:await stream.aclose()
            for _ in range(4):await asyncio.sleep(0)
            rows.append(dict(name=name,result=result,returned=source.returned if name!='empty-uplink' else None,closed=len(closed),listeners=len(carrier.signal._listeners)+len(peer.signal._listeners)))
        finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_invocation.mts','Actual resource-authorized Gateway core unary/duplex streams, single-consumer uplink, strict item rejection, undefined SRC items, peer/carrier cancellation, early close, unread release and listener cleanup; network mux/admission remains separate.',
        [Path(__file__).resolve(),ROOT/'dsh/typert/invocation.py',ROOT/'dsh/typert/gateway_core.py'])
