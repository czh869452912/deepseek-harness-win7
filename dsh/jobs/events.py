"""Scope-aware current job event routing; each subscription owns its effect."""
from dsh.core.scope import AnonymousEntries,scope_of


class JobLayer:
    def __init__(self):self.controllers,self.scoped=AnonymousEntries(),AnonymousEntries()
    def is_empty(self):return self.controllers.is_empty() and self.scoped.is_empty()


class JobEventHub:
    def __init__(self,layers,warn):self.layers,self.warn=layers,warn;self.unscoped=[]

    def subscribe(self,ctx,filter,listener):
        subscription=dict(filter=filter,listener=listener)
        if filter.get('owners')=='scope':
            return self.layers.effect(ctx,lambda layer:layer.scoped.append(subscription),dict(label='jobs.events.subscribe()'))
        def setup():
            self.unscoped.append(subscription)
            def dispose():
                for index,value in enumerate(self.unscoped):
                    if value is subscription:self.unscoped.pop(index);break
            return dispose
        return ctx.effect(setup,'jobs.events.subscribe()')

    def emit(self,event,owner):
        identity=owner.id if owner is not None else None
        for subscription in list(self.unscoped):
            filter=subscription['filter']
            if 'owner' in filter and identity is not None and identity!=filter['owner']:continue
            self.deliver(subscription,event)
        for subscription in self.layers.global_layer.scoped.values():self.deliver(subscription,event)
        for layer in self.layers.chain_layers(scope_of(owner.ctx) if owner is not None else None):
            for subscription in layer.scoped.values():self.deliver(subscription,event)

    def deliver(self,subscription,event):
        try:subscription['listener'](event)
        except Exception as error:self.warn('jobs: event listener threw on %s: %s' % (event['type'],error))
