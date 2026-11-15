"""Cordis-owned default resource declarations for the rc022 candidate registry."""
from types import MappingProxyType, SimpleNamespace
from dsh.core.session.json import UNDEFINED
from dsh.typert.stores import ChangeSource, LookupView, field, segment, wire_name, resolve_async


class ResourceStore:
    def __init__(self):
        self.declarations, self.changes = {}, ChangeSource()


class ResourceView:
    def __init__(self, ctx, store):
        self.ctx, self.store = ctx, store

    def register(self, kind, declaration):
        segment('resource kind', kind)
        if kind == 'global':
            raise ValueError('typert: resource kind "global" is reserved for the built-in global resource')
        if kind in self.store.declarations:
            raise ValueError('typert: resource kind "%s" is already registered' % kind)
        resolver, name = field(declaration, 'resolve', UNDEFINED), field(declaration, 'field', UNDEFINED)
        if resolver is not UNDEFINED:
            provider = dict(resolve=resolver)
        elif name is not UNDEFINED:
            wire_name('resource field', name)
            provider = dict(field=name)
        else:
            raise ValueError('typert: resource kind "%s" declares neither a field nor a resolve function' % kind)
        entry = dict(provider=provider)
        def setup():
            self.store.declarations[kind] = entry
            self.store.changes.emit('resource', kind)
            def dispose():
                if self.store.declarations.get(kind) is entry:
                    del self.store.declarations[kind]
                    self.store.changes.emit('resource', kind)
            return dispose
        return self.ctx.effect(setup, 'typert.resources.register()')

    def get(self, kind):
        entry = self.store.declarations.get(kind)
        return entry['provider'] if entry is not None else None

    def entries(self):
        return [MappingProxyType(dict(kind=kind, **entry['provider'])) for kind, entry in self.store.declarations.items()]

    def subscribe(self, listener):
        return self.store.changes.subscribe(self.ctx, listener)


class ResourceLookupView(LookupView):
    def get(self, key):
        entry = self.store.providers.get(key)
        if entry is None:
            return None
        provider, resolver = entry['provider'], self.store.resolvers.get(key)
        if resolver is None:
            return provider
        values = {name: field(provider, name) for name in ('parameter', 'wire', 'hostTypeSymbol', 'wireTypeSymbol')}
        resource = field(provider, 'resource', UNDEFINED)
        if resource is not UNDEFINED:
            values['resource'] = resource
        return SimpleNamespace(**values, resolve=lambda identity: resolve_async(resolver['provider'], identity))
