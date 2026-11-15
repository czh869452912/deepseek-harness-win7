"""rc.3 concrete Agent factory over current Session handles and request machine."""
from dsh.core.agent import AgentHandle
from dsh.core.agent_lifecycle_current import CurrentAgentLifecycleService, CurrentAgentLifecyclePlugin
from dsh.core.agent_dispatch_current import emit_agent_event
from dsh.core.react_loop_current import ReactLoopAgent
from dsh.core.inbox_current import INBOX_PROJECTION_DEFINITION


class CurrentAgentLoopService(CurrentAgentLifecycleService):
    def __init__(self, ctx, config=None):
        super().__init__(ctx, config)
        # Profile shutdown retires Agents before concurrent provider teardown.
        # Their final writer/cache barriers still need the live service graph.
        ctx.on('app/stopping', self.teardown)
        self._inbox_projection_handle = None

    async def initialize_projections(self):
        projections = self._runtime['ctx'].get('sessionProjections')
        if getattr(projections, 'format_version', 3) == 4:
            self._inbox_projection_handle = await projections.register(INBOX_PROJECTION_DEFINITION)

    async def _publish_preparation(self, tx, preparation, options, setup, source):
        session = preparation.session
        tx.assert_live()
        runtime_ctx = self._runtime['ctx']
        def lifecycle():
            reader = (self._inbox_projection_handle.readerFor(session)
                      if self._inbox_projection_handle is not None else None)
            tx.agent = ReactLoopAgent(runtime_ctx, session, options, inbox_reader=reader)
            tx.scope = tx.agent.scope
            yield tx.scope.raw_dispose
            yield tx.owner_dispose
        runtime_ctx.effect(lifecycle, label='agentLoop.lifecycle(%s)' % session.id)
        if setup is not None:
            result = await tx.race(lambda: self._invoke_setup(setup, tx.agent))
            commit = getattr(result, 'commit', None)
            if callable(commit):
                await tx.race(commit)
        tx.assert_live()
        await self._before_publish(tx, session)
        tx.assert_live()
        sessions, agents = tx.agent.ctx.get('sessions'), runtime_ctx.get('agents')
        tx.detach_session = sessions.enter(session)
        tx.detach_agent = agents.enter(tx.agent, owner=tx.parent_agent)
        sessions.announce(session)
        tx.assert_live()
        agents.announce(tx.agent)
        tx.assert_live()
        # send() already starts this machine, including from this notification.
        emit_agent_event(runtime_ctx, tx.agent, 'agent/session-start', dict(source=source))
        tx.assert_live()
        return AgentHandle(tx.agent, tx.dispose)


class CurrentAgentLoopPlugin(CurrentAgentLifecyclePlugin):
    _service_class = CurrentAgentLoopService
