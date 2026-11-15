"""Candidate v4 subagent service over the unified execution manager."""
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.volatile import is_volatile
from dsh.typert.remote import TypertRemoteService
from dsh.core.session.json import UNDEFINED
from dsh.core.json_schema import assert_object_json_schema
from dsh.subagent.catalog import CATALOG
from dsh.subagent.composition_current import assert_max_depth
from dsh.subagent.errors import SubagentError
from dsh.subagent.lifecycle_current import LifecycleEmitter
from dsh.subagent.list_children import list_children,list_descendants
from dsh.subagent.manager import SubagentManager
from dsh.subagent.projections import IDENTITY,TIMING4


CONFIG = Schema.object(dict(
    maxDepth=Schema.number().step(1).min(0).max(9007199254740991).default(1).volatile(),
    maxActiveSubagents=Schema.number().step(1).min(1).max(9007199254740991).default(8).volatile()))


class SubagentRuntime(TypertRemoteService):
    def __init__(self, ctx, config, catalog_projection, identity_projection):
        super().__init__(ctx,'subagents')
        self.config,self.providers,self.manager = config,{},None
        self.emit_lifecycle = LifecycleEmitter(self.ctx,self)
        def bind(child_ctx):
            from types import SimpleNamespace
            manager = SubagentManager(child_ctx,SimpleNamespace(
                identityOf=lambda session:identity_projection.stateOf(session).get('identity'),
                catalogOf=lambda session:CATALOG['wire']['view'](catalog_projection.stateOf(session)),
                emitLifecycle=self.emit_lifecycle),lambda:self.setting('maxActiveSubagents'))
            self.manager = manager
            def clear():
                if self.manager is manager:
                    self.manager = None
            child_ctx.effect(lambda:clear,'subagents.managerBinding()')
        ctx.inject(['agents'],bind)

    def setting(self, name):
        value = self.config[name]
        return value.get() if is_volatile(value) else value

    def resolveMaxDepth(self, configured=UNDEFINED):
        if configured == 'provider-managed':
            return UNDEFINED
        if configured is not UNDEFINED:
            return configured
        depth = self.setting('maxDepth')
        assert_max_depth(depth)
        return depth

    def registerProvider(self, provider):
        name = provider.name
        if getattr(provider,'start',None) is None and getattr(provider,'prepareContinuable',None) is None:
            raise SubagentError('subagent provider "%s" must implement start or prepareContinuable' % name,'UNSUPPORTED_CAPABILITY')
        def setup():
            if name in self.providers:
                raise SubagentError('a subagent provider named "%s" is already registered' % name,'DUPLICATE_PROVIDER')
            self.providers[name] = provider
            def remove():
                self.providers.pop(name,None)
                self.emit_lifecycle('subagent/provider-removed',name)
            yield remove
            self.ctx.emit('subagent/provider-added',provider)
        return self.ctx.effect(setup,'subagents.registerProvider()')

    def getProvider(self, name):
        return self.providers.get(name)

    def expect_provider(self, name):
        provider = self.getProvider(name)
        if provider is None:
            raise SubagentError('no subagent provider registered for "%s"' % name,'NO_PROVIDER')
        return provider

    def assert_provider_current(self, provider):
        if self.getProvider(provider.name) is not provider:
            raise SubagentError('subagent provider "%s" changed during startup; retry the delegation' % provider.name,'PROVIDER_CHANGED')

    def require_manager(self):
        if self.manager is None:
            raise SubagentError('continuable subagents require the agents service','CONTINUATION_UNAVAILABLE')
        return self.manager

    @staticmethod
    def assert_capabilities(provider, request):
        if 'agentPreset' in request and (not provider.capabilities.get('agentPreset') or getattr(provider,'inheritsParentContext',False)):
            raise SubagentError('subagent provider "%s" does not support independent agent preset selection' % provider.name,'UNSUPPORTED_CAPABILITY')
        for key,capability in (('agentOptions','agentOptions'),('outputSchema','outputSchema'),('maxDepth','depthLimit')):
            if key in request and not provider.capabilities.get(capability):
                raise SubagentError('subagent provider "%s" does not support the "%s" capability' % (provider.name,capability),'UNSUPPORTED_CAPABILITY')

    async def startActivation(self, spec):
        provider = self.expect_provider(spec['provider'])
        prepare = getattr(provider,'prepareContinuable',None)
        if 'childId' in spec and prepare is None:
            raise SubagentError('reserved child ids require a local backend','UNSUPPORTED_CAPABILITY')
        assert_max_depth(spec.get('maxDepth',UNDEFINED))
        self.assert_capabilities(provider,spec)
        manager = self.require_manager()
        agents = self.ctx.get('agents')
        if agents is None or agents.get(spec['parent'].id) is not spec['parent']:
            raise SubagentError('subagent creation requires the exact live parent agent','UNAUTHORIZED')
        if 'outputSchema' in spec:
            assert_object_json_schema(spec['outputSchema'])
        if prepare is not None:
            def checked(request):
                self.assert_provider_current(provider)
                return prepare(request)
            return await manager.start_local(spec,checked)
        start = provider.start
        def checked(request):
            self.assert_provider_current(provider)
            return start(request)
        return await manager.start_external(spec,checked)

    def rootOf(self, caller):
        return self.require_manager().root_of(caller)

    def namesOf(self, agent):
        return self.require_manager().names_of(agent)

    async def resolveName(self, caller, name, signal):
        return await self.require_manager().resolve_name(caller,name,signal)

    async def waitForTreeWork(self, root):
        return False if self.manager is None else await self.manager.wait_for_tree_work(root)

    async def sendMessage(self, sender, target_id, content, options):
        return await self.require_manager().send_message(sender,target_id,content,options)

    def interrupt(self, target_id, authority):
        if self.manager is not None:
            self.manager.interrupt(target_id,authority)

    async def drainDescendants(self, parents):
        if self.manager is not None:
            await self.manager.drain_descendants(parents)

    async def listChildren(self, identity, signal=None):
        return await list_children(self.ctx,identity,signal)

    async def listDescendants(self, identity, signal=None):
        return await list_descendants(self.ctx,identity,signal)

    # Candidate local facade. Remote resource declarations are activated with
    # the coordinated Gateway authorization migration, before production use.
    async def prompt(self, request, signal):
        from dsh.subagent.control import prompt
        return await prompt(self,request,signal)

    def interruptByUser(self, childSessionId):
        from dsh.subagent.control import interrupt_by_user
        return interrupt_by_user(self,childSessionId)


class SubagentPlugin(Plugin):
    id = 'subagent'
    inject = ['workingDirectory','sessionProjections']
    Config = CONFIG

    async def apply(self, ctx):
        projections = ctx.get('sessionProjections')
        catalog = await projections.register(CATALOG)
        await projections.register(TIMING4)
        identity = await projections.register(IDENTITY)
        if ctx.fiber.uid is None:
            return
        SubagentRuntime(ctx,self.config,catalog,identity)
