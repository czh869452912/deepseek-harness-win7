"""Observe associated members through services and generic tracked values."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def native():
    from dsh.cordis import Context, Service
    from dsh.cordis.utils import symbols, get_traceable
    result = {}
    for generic in (False, True):
        ctx = Context()
        class Api(Service):
            def __init__(self, owner):
                super().__init__(owner, 'api')
                self.label = 'own'
            def read(self):
                return self.ctx.api.secret
        class Tracked:
            def __init__(self, owner):
                self.ctx = owner
                self.label = 'own'
                setattr(self, symbols.tracker, dict(associate='api', property='ctx'))
            def read(self):
                return self.ctx.api.secret
        def values(owner):
            owner.provide('api.secret', 'provider')
        await ctx.plugin(values)
        instances = []
        def provide(owner):
            api = Tracked(owner) if generic else Api(owner)
            if generic:
                owner.provide('api', api)
            instances.append(api)
        await ctx.inject(['api.secret'], provide)
        access = []
        def extensions(owner):
            def read(hook_ctx, receiver, error):
                access.append([hook_ctx.fiber is consumer.ctx.fiber,
                    getattr(receiver, symbols.original) is instances[0]])
                return 'extension'
            def write(hook_ctx, value, receiver, error):
                access.append([hook_ctx.fiber is consumer.ctx.fiber,
                    getattr(receiver, symbols.original) is instances[0], value])
                return True
            owner.accessor('api.label', dict(get=read, set=write))
        extension = await ctx.plugin(extensions)
        realm = ctx.isolate('api.secret')
        realm.provide('api.secret', 'caller')
        consumer = await realm.inject(['api', 'api.secret'], lambda owner: None)
        proxy = consumer.ctx.api
        result[str(generic).lower()] = [proxy.secret, proxy.read(), proxy.label]
        proxy.label = 'written'
        result[str(generic).lower()].extend([access, instances[0].label])
        await extension.dispose()
        result[str(generic).lower()].append(proxy.label)
        denied = []
        def no_inject(owner):
            try:
                owner.api.secret
            except RuntimeError as error:
                denied.append(str(error))
        await ctx.inject(['api'], no_inject)
        result[str(generic).lower()].append(denied)
        metadata = consumer.ctx.extend({'tag': 'caller-metadata'})
        class Meta:
            def __init__(self):
                self.ctx = ctx
                setattr(self, symbols.tracker, dict(property='ctx'))
            def read(self):
                return self.ctx.tag
        result[str(generic).lower()].append(get_traceable(metadata, Meta()).read())
        await ctx.fiber.dispose()
    return result


if __name__ == '__main__':
    probe.native = native
    probe.main(observer='rc022_associated.mts', scope='Associated service reads, writes, accessor receiver, reversible extensions and definition/use injection scopes.',
        extra_inputs=[Path(__file__).resolve(), ROOT/'dsh/cordis/service.py', ROOT/'dsh/cordis/utils.py',
            ROOT/'dsh/cordis/context.py', ROOT/'dsh/cordis/reflect.py'])
