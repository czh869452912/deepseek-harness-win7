"""Service code retains definition injection while effects follow consumption."""
import pytest

from dsh.cordis import Context, Service
from dsh.cordis.utils import get_traceable, symbols


@pytest.mark.asyncio
async def test_service_methods_getters_and_invocation_keep_definition_scope():
    ctx=Context();ctx.provide('secret','provider');seen=[];disposed=[]
    class Api(Service):
        def __init__(self,owner):
            super().__init__(owner,'api')
            setattr(self,Service.invoke,self.read)
        def read(self):
            owner=self.ctx.fiber.uid
            self.ctx.effect(lambda:lambda:disposed.append(owner))
            self.ctx.logger.info('api read')
            return self.ctx.secret,owner
        @property
        def value(self):return self.ctx.secret
    provider=ctx.inject(['secret'],lambda owner:Api(owner));await provider
    realm=ctx.isolate('secret');realm.provide('secret','caller')
    def consume(owner):
        proxy=owner.api
        seen.extend([proxy.read(),proxy.value,proxy(),getattr(proxy,symbols.caller) is owner,proxy.ctx is owner])
        proxy.ctx=ctx
        assert proxy.ctx is owner
    consumer=realm.inject(['api'],consume);await consumer
    assert seen==[('provider',consumer.uid),'provider',('provider',consumer.uid),True,True]
    uid=consumer.uid;await consumer.dispose();assert disposed==[uid,uid]
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_caller_injection_does_not_grant_service_definition_new_permissions():
    ctx=Context();seen=[]
    secret_provider=ctx.plugin(lambda owner:owner.provide('secret','hidden'));await secret_provider
    class Api(Service):
        def read(self):return self.ctx.secret
    provider=ctx.plugin(lambda owner:Api(owner,'api'));await provider
    def consume(owner):
        with pytest.raises(RuntimeError,match='without inject'):owner.api.read()
        seen.append(owner.secret)
    consumer=ctx.inject(['secret','api'],consume);await consumer
    assert seen==['hidden']
    proxy=get_traceable(ctx,ctx.get('api'))
    with pytest.raises(RuntimeError,match='without inject'):proxy.read()
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_no_shadow_tracker_exposes_caller_without_changing_public_context():
    ctx=Context();definition=ctx.extend();use_site=ctx.extend()
    shadow=use_site.extend({symbols.shadow:definition})
    class Tracked:
        def read(self):return self.ctx,getattr(self,symbols.caller)
    tracked=Tracked();tracked.ctx=definition
    setattr(tracked,symbols.tracker,{'property':'ctx','noShadow':True})
    proxy=get_traceable(shadow,tracked)
    assert proxy.read()==(use_site,definition)
    setattr(proxy,symbols.caller,ctx)
    assert getattr(proxy,symbols.caller) is definition
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_inherited_method_and_property_keep_their_original_definition():
    ctx=Context();ctx.provide('secret',7);seen=[]
    class Api(Service):
        def read(self):return self.ctx.secret
        @property
        def value(self):return self.read()
    values=[]
    provider=ctx.inject(['secret'],lambda owner:values.append(Api(owner,'api')));await provider
    derived=values[0]._extend({'extra':True})
    consumer=ctx.plugin(lambda owner:seen.extend([get_traceable(owner,derived).read(),get_traceable(owner,derived).value]));await consumer
    assert seen==[7,7]
    await ctx.fiber.dispose()
