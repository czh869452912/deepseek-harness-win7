"""Pair pre-lookup access ordering and invocation-bound service receivers."""
import asyncio
import inspect
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    room=dict(kind='session',id='a');other=dict(kind='session',id='b');global_=dict(kind='global')
    return [
        dict(name='global-denied',method='open',args={},held=[]),
        dict(name='global-allowed',method='open',args={},held=[global_]),
        dict(name='lookup-denied',method='lookup',args=dict(agentId='a'),held=[]),
        dict(name='lookup-allowed',method='lookup',args=dict(agentId='a'),held=[room]),
        dict(name='lookup-invalid',method='lookup',args=dict(agentId=None),held=[room]),
        dict(name='scope-denied',method='scoped',args=dict(scopeId='a'),held=[]),
        dict(name='scope-allowed',method='scoped',args=dict(scopeId='a'),held=[room]),
        dict(name='scope-invalid',method='scoped',args=dict(scopeId=[]),held=[room]),
        dict(name='reader-all-required',method='several',args=dict(ids=['a','b']),held=[room]),
        dict(name='reader-all-allowed',method='several',args=dict(ids=['a','b']),held=[room,other]),
        dict(name='reader-empty',method='several',args=dict(ids=[]),held=[global_]),
        dict(name='unknown-field',method='lookup',args=dict(agentId='a',extra=True),held=[room]),
        dict(name='missing-lookup',method='lookup',args={},held=[global_]),
        dict(name='owner-bypass',method='lookup',args=dict(agentId='a'),held=[],owner=True),
        dict(name='nested-default-denied',method='read',args=dict(request=dict(sessionId='b')),held=[room]),
        dict(name='nested-default-allowed',method='read',args=dict(request=dict(sessionId='a')),held=[room]),
        dict(name='item-filter',method='list',args={},held=[global_,room]),
        dict(name='strict-strip-before-policy',method='annotate',args=dict(request=dict(title='Title',sessionId='b')),held=[global_]),
        dict(name='strict-input-before-policy',method='annotate',args=dict(request=dict(title=7)),held=[global_]),
        dict(name='disposed-first',method='absent',args=dict(unexpected=7),held=[],disposed=True),
    ]


async def observe(use_gateway=False):
    from types import SimpleNamespace as NS
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.remote import Remote,RemoteScope,TypertRemoteService
    from dsh.typert.authorized_calls import AuthorizedCallResolver
    from dsh.typert.artifact import Schema
    from dsh.host.connection.peer import Peer
    rows=[]
    for case in cases():
        ctx=Context();await ctx.plugin(CurrentTypertRegistry);await ctx.plugin(RemoteAccessService);counts=dict(lookup=0,context=0,method=0,policy=0)
        class Fixture(TypertRemoteService):
            inject=['remoteAccess']
            def __init__(self, child):super().__init__(child,'fixture')
            def seen(self, data=None):
                counts['method']+=1
                invocation=self.ctx.invocation
                return dict(principal=invocation.peer.principal,service=invocation.service,wire=invocation.request['args'],data=data)
            @Remote
            def open(self):return self.seen()
            @Remote
            def lookup(self, agent):return self.seen(dict(id=agent.id))
            @RemoteScope('agentScope')
            def scoped(self):return self.seen()
            @Remote(dict(resources=dict(session=lambda ids:ids)))
            def several(self, ids):return self.seen(ids)
            @Remote
            def read(self, request):return self.seen(request)
            @Remote
            def annotate(self, request):return self.seen(request)
            @Remote
            def list(self):return self.seen([identity for identity in ['a','b'] if self.ctx.remoteAccess.allows(dict(kind='session',id=identity))])
        try:
            await ctx.plugin(Fixture)
            if use_gateway:
                from dsh.typert.gateway_core import AuthorizedGatewayCore
                await ctx.plugin(AuthorizedGatewayCore)
            ctx.typert.resources.register('session',dict(field='sessionId'))
            def lookup(identity):counts['lookup']+=1;return NS(id=identity)
            def context(identity):counts['context']+=1;return ctx
            ctx.typert.lookups.register('agent',NS(parameter='agent',wire='agentId',hostTypeSymbol='Agent',wireTypeSymbol='Id',resource='session',resolve=lookup))
            ctx.typert.contexts.registerHost('agentScope',NS(wire='scopeId',wireTypeSymbol='Id',resource='session',identity=lambda _:None,resolve=context))
            def bindings(_):
                counts['policy']+=1
                return [dict(resource=resource,role=dict(actions=['fixture/'+name for name in ['open','lookup','scoped','several','read','list','annotate']])) for resource in case['held']]
            ctx.remoteAccess.registerPolicy('guest',dict(bindings=bindings))
            codec=dict(mode='strict',typeSymbol='Request',schema=Schema('object', (dict(title=Schema('string')),)))
            descriptor=dict(id='fixture#annotate',service='fixture',namespace='fixture',method='annotate',parameters=[dict(name='request',wire='request',source='json',codec=codec)],result=dict(mode='src-json'),invocation=dict(kind='direct'))
            ctx.typert.register(dict(package='fixture',face='host',model={},schemas=[],invocations=[descriptor]))
            peer=Peer(ctx,dict(principal=dict(kind='owner') if case.get('owner') else dict(kind='guest',guest='a')))
            if case.get('disposed'):await peer.dispose()
            request=dict(namespace='fixture',method=case['method'],args=case['args'],peer=peer,signal=NEVER_ABORTED)
            resolver=AuthorizedCallResolver(ctx)
            try:
                if use_gateway:
                    value=await ctx.typertGateway.invoke(request)
                else:
                    prepared=await resolver.resolve(request)
                    invocation=NS(request=dict(namespace='fixture',method=case['method'],args=case['args']),service='fixture',peer=peer,signal=NEVER_ABORTED)
                    method,args=resolver.bind(prepared,invocation);value=method(*args)
                    if inspect.isawaitable(value):value=await value
                result=dict(value=value)
            except Exception as error:result=dict(error=dict(code=error.code,details=error.details))
            rows.append(dict(name=case['name'],**result,counts=dict(counts)))
        finally:await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_authorized_calls.mts','Pre-lookup resource authorization and denial side effects, strict JSON validation/stripping before policy, original wire invocation, item filtering and scoped/lookup activation, owner and disposed Peer ordering. Native resolver/binder seam versus actual Source Gateway unary calls; carrier/uplink lifetime remains separate.',
        [Path(__file__).resolve(),ROOT/'dsh/typert/authorized_calls.py',ROOT/'dsh/host/connection/peer.py'],prepare=prepare)
