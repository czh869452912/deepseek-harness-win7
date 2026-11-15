"""rc.3 concrete Agent factory over current Session handles and request machine."""
import asyncio

from dsh.core.agent import AgentHandle, AgentOptions
from dsh.core.session.json import UNDEFINED
from dsh.core.agent_lifecycle_current import CurrentAgentLifecycleService, CurrentAgentLifecyclePlugin
from dsh.core.agent_dispatch_current import emit_agent_event
from dsh.core.react_loop_current import ReactLoopAgent
from dsh.core.inbox_current import INBOX_PROJECTION_DEFINITION
from dsh.core.model_selection import MODEL_SELECTION_PROJECTION_DEFINITION


class CurrentAgentLoopService(CurrentAgentLifecycleService):
    def __init__(self, ctx, config=None):
        super().__init__(ctx, config)
        # Profile shutdown retires Agents before concurrent provider teardown.
        # Their final writer/cache barriers still need the live service graph.
        ctx.on('app/stopping', self.teardown)
        self._inbox_projection_handle = None
        self._model_projection_handle = None

    async def initialize_projections(self):
        projections = self._runtime['ctx'].get('sessionProjections')
        if getattr(projections, 'format_version', 3) == 4:
            self._model_projection_handle = await projections.register(MODEL_SELECTION_PROJECTION_DEFINITION)
            self._inbox_projection_handle = await projections.register(INBOX_PROJECTION_DEFINITION)

    @staticmethod
    def _request_options(request):
        options = request.get('agentOptions', request.get('options'))
        if not isinstance(options, dict):return options
        return AgentOptions(provider=options.get('provider'), model=options.get('model'),
                            reasoning_effort=options.get('reasoningEffort', options.get('reasoning_effort')),
                            max_tokens=options.get('maxTokens', options.get('max_tokens')))

    async def createAgent(self, owner_ctx, request):
        return await self.create_agent(request.get('sessionId'), self._request_options(request),
                                       request.get('meta'), request.get('setup'), request.get('seed'),
                                       request.get('signal'), owner_ctx,
                                       request.get('inheritedEventCount', UNDEFINED), request.get('parentAgent'))

    async def resume(self, resume_session_id, options=None, setup=None, **kwargs):
        if hasattr(resume_session_id, 'fiber') and isinstance(options, dict):
            owner_ctx, request = resume_session_id, options
            return await super().resume(request.get('resumeSessionId'), self._request_options(request),
                                        request.get('setup'), request.get('signal'), owner_ctx,
                                        parent_agent=request.get('parentAgent'))
        return await super().resume(resume_session_id, options, setup, **kwargs)

    async def _publish_preparation(self, tx, preparation, options, setup, source):
        session = preparation.session
        tx.assert_live()
        runtime_ctx = self._runtime['ctx']
        def lifecycle():
            reader = (self._inbox_projection_handle.readerFor(session)
                      if self._inbox_projection_handle is not None else None)
            model_reader = (self._model_projection_handle.readerFor(session)
                            if self._model_projection_handle is not None else None)
            tx.agent = ReactLoopAgent(runtime_ctx, session, options, inbox_reader=reader, model_reader=model_reader,
                                      lifetime_signal=tx.controller.signal if getattr(session,'format_version',3) == 4 else None)
            tx.scope = tx.agent.scope
            yield tx.scope.raw_dispose
            yield tx.owner_dispose
        runtime_ctx.effect(lifecycle, label='agentLoop.lifecycle(%s)' % session.id)
        if getattr(session, 'format_version', 3) == 4:
            return await self._publish_current(tx, session, setup, source)
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
        announcement = agents.announce(tx.agent, source, tx.controller.signal) if getattr(agents, 'format_version', 3) == 4 else agents.announce(tx.agent)
        if announcement is not None:
            await announcement
        tx.assert_live()
        # send() already starts this machine, including from this notification.
        emit_agent_event(runtime_ctx, tx.agent, 'agent/session-start', dict(source=source))
        tx.assert_live()
        return AgentHandle(tx.agent, tx.dispose)

    async def _publish_current(self, tx, session, setup, source):
        runtime_ctx=self._runtime['ctx']
        async def publish(_signal):
            tx.publication=asyncio.get_running_loop().create_future()
            try:
                tx.assert_live()
                await self._before_publish(tx,session)
                tx.assert_live()
                sessions,agents=tx.agent.ctx.get('sessions'),runtime_ctx.get('agents')
                tx.detach_session=sessions.enter(session)
                sessions.announce(session)
                tx.assert_live()
                if setup is not None:
                    result=await tx.race(lambda:self._invoke_setup(setup,tx.agent))
                    tx.assert_live()
                    commit=getattr(result,'commit',None)
                    if callable(commit):commit()
                tx.assert_live()
                tx.detach_agent=agents.enter(tx.agent)
                await agents.announce(tx.agent,source,tx.controller.signal)
                tx.assert_live()
                tx.mark_ready()
                return AgentHandle(tx.agent,tx.dispose)
            except BaseException:
                tx.agent.cancel(dict(kind='disposed'),dict(keepInbox=True))
                raise
            finally:
                tx.publication.set_result(None)
                tx.publication=None
        return await tx.agent.runMaintenance(publish)


class CurrentAgentLoopPlugin(CurrentAgentLifecyclePlugin):
    _service_class = CurrentAgentLoopService
