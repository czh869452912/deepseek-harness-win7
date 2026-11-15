"""rc.3 Agent registry: explicit lineage and identity-scoped notifications."""
from dsh.core.agent import AgentRegistry, AgentPlugin
from dsh.core.agent_dispatch_current import agent_events, emit_agent_event
from dsh.cordis.utils import _js_call_callback


class CurrentAgentRegistry(AgentRegistry):
    def __init__(self, ctx=None, format_version=3):
        self.format_version = format_version
        self._turn_boundary_handle = None
        super().__init__(ctx)

    async def initialize(self):
        if self.format_version == 4:
            from dsh.core.turn_boundary import TURN_BOUNDARY_DEFINITION
            self._turn_boundary_handle = await self.ctx.get('sessionProjections').register(TURN_BOUNDARY_DEFINITION)

    def turnBoundaryOf(self, session):
        if self.format_version == 4:
            return self._turn_boundary_handle.stateOf(session)
        return self.ctx.get('sessionProjections').stateOf(session,'turnBoundary')

    def _host_context_adapter(self):
        return dict(wire='agentId', wireTypeSymbol='@deepseek-ai/dsh-session/types#SessionId',
                    resolve=lambda sid: self.get(sid).ctx if self.get(sid) is not None else None)

    def _factory_request_options(self, request):
        return dict(parent_agent=request.get('parentAgent', request.get('parent_agent')))

    def _emit_subject(self, name, agent):
        if name != 'agent/created':
            emit_agent_event(self.ctx, agent, name, {})
            return
        # Creation remains a synchronous veto boundary; only its returned
        # promise rejection is contained. Ordinary Agent notifications are not vetoes.
        dispatch = agent_events(self.ctx, agent)
        payload = dict(agent=agent)
        for callback in self.ctx.events.dispatch('emit', [dispatch.carrier, name, payload]):
            dispatch._settle(_js_call_callback(callback, (payload,), maximum=1), name)


class CurrentAgentPlugin(AgentPlugin):
    async def apply(self, ctx):
        projections = ctx.get('sessionProjections')
        registry = CurrentAgentRegistry(ctx,getattr(projections,'format_version',3))
        ctx.set_service('agents',registry)
        await registry.initialize()
