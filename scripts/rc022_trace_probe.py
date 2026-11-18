"""Compare definition/consumption contexts with unchanged fixed Source."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import Context, Service
    from dsh.cordis.utils import symbols,get_traceable
    result={};ctx=Context();disposed=[];seen=[];ctx.provide('secret','provider')
    class Api(Service):
        def __init__(self,owner):
            super().__init__(owner,'api');setattr(self,Service.invoke,self.read)
        def read(self):
            owner=self.ctx.fiber
            self.ctx.effect(lambda:lambda:disposed.append(owner));self.ctx.logger.info('api read')
            return self.ctx.secret,owner
        @property
        def value(self):return self.ctx.secret
    def provide(owner):Api(owner)
    provider=ctx.inject(['secret'],provide);await provider
    realm=ctx.isolate('secret');realm.provide('secret','caller')
    def consume(owner):
        proxy=owner.api;first=proxy.read();second=proxy()
        seen.extend([first[0],first[1] is owner.fiber,proxy.value,second[0],second[1] is owner.fiber,proxy.ctx is owner,getattr(proxy,symbols.caller) is owner,getattr(proxy,symbols.original) is getattr(ctx.get('api'),symbols.original)])
        proxy.ctx=ctx;seen.append(proxy.ctx is owner)
    consumer=realm.inject(['api'],consume);await consumer
    result['allowed']=[seen,[row.fiber() is provider.ctx.fiber for row in ctx.logger.buffer if row.args[0]=='api read']]
    owner=consumer.ctx.fiber;await consumer.dispose();result['cleanup']=[item is owner for item in disposed];await ctx.fiber.dispose()
    ctx=Context()
    def secret(owner):owner.provide('secret','hidden')
    await ctx.plugin(secret)
    class Api(Service):
        def read(self):return self.ctx.secret
    def provide(owner):Api(owner,'api')
    await ctx.plugin(provide);seen=[]
    def consume(owner):
        try:owner.api.read()
        except RuntimeError as error:seen.append(str(error))
        seen.append(owner.secret)
    await ctx.inject(['secret','api'],consume)
    try:get_traceable(ctx,ctx.get('api')).read()
    except RuntimeError as error:seen.append(str(error))
    result['denied']=seen;await ctx.fiber.dispose()
    ctx=Context();values=[];seen=[];ctx.provide('secret',7)
    class Api(Service):
        def read(self):return self.ctx.secret
        @property
        def value(self):return self.read()
    def provide(owner):values.append(Api(owner,'api'))
    await ctx.inject(['secret'],provide);derived=values[0]._extend({'extra':True})
    def consume(owner):
        proxy=get_traceable(owner,derived);seen.extend([proxy.read(),proxy.value])
    await ctx.plugin(consume);result['inherited']=seen;await ctx.fiber.dispose()
    ctx=Context();definition=ctx.extend();use_site=ctx.extend();shadow=use_site.extend({symbols.shadow:definition})
    class Tracked:
        def read(self):return [self.ctx is use_site,getattr(self,symbols.caller) is definition]
    tracked=Tracked();tracked.ctx=definition;setattr(tracked,symbols.tracker,{'property':'ctx','noShadow':True})
    proxy=get_traceable(shadow,tracked);result['noShadow']=proxy.read();setattr(proxy,symbols.caller,ctx)
    result['noShadow'].append(getattr(proxy,symbols.caller) is definition);await ctx.fiber.dispose()
    ctx=Context();seen=[];disposed=[];ctx.provide('secret','provider')
    class Api(Service):
        def scope(self):return self.ctx.extend({'marker':'derived'})
        def pluginType(self):return Api
        def mount(self):
            def install(child):
                seen.extend([child.secret,child.marker]);child.effect(lambda:lambda:disposed.append('child'))
            return self.ctx.extend({'marker':'derived'}).inject(['secret'],install)
    await ctx.plugin(lambda owner:Api(owner,'api'))
    realm=ctx.isolate('secret');realm.provide('secret','caller')
    async def consume(owner):
        scope=owner.api.scope();seen.extend([scope.marker,symbols.shadow in scope.__dict__,owner.api.pluginType() is Api])
        child=await owner.api.mount();seen.append(child.parent.fiber is owner.fiber)
    consumer=await realm.inject(['api'],consume)
    await consumer.dispose();result['nested']=[seen,disposed];await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main(observer='rc022_trace.mts',scope='Definition-site injection, consumption-site effects and public context, callable/getter/inherited service methods, logger ownership and readonly tracing context.',
               extra_inputs=[ROOT/'dsh/cordis/service.py',ROOT/'dsh/cordis/utils.py',ROOT/'dsh/cordis/context.py',ROOT/'dsh/cordis/logger.py',Path(__file__).resolve(),ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/cordis/src/utils.ts',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/cordis/src/service.ts',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/cordis/src/reflect.ts',ROOT/'.goose/out/rc022-prep-20261114-01/source/vendor/cordis/src/logger.ts'])
