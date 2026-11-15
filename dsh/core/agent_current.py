"""rc.3 Agent registry: explicit lineage and identity-scoped notifications."""
import asyncio
import contextvars
import inspect

from dsh.core.agent import AgentRegistry, AgentPlugin
from dsh.core.agent_dispatch_current import AgentEventDispatch, agent_carrier, agent_events, emit_agent_event
from dsh.cordis.utils import _js_call_callback, _js_error_to_string, get_traceable, symbols
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.fiber import FiberState


class CurrentAgentRegistry(AgentRegistry):
    def __init__(self, ctx=None, format_version=3):
        self.format_version = format_version
        self._turn_boundary_handle = None
        super().__init__(ctx)
        if format_version == 4:
            self._initiator_runtime = dict(
                ctx=ctx, value=contextvars.ContextVar('agent-initiator', default=None),
                runs=contextvars.ContextVar('agent-initiator-run', default=None), disposal=None)
            def unloading(fiber, *_args):
                if getattr(fiber, 'state', None) == FiberState.UNLOADING and self._has_lifecycle_ancestor(fiber):
                    self.close_initiators()
            ctx.on('internal/status', unloading)
            def lifecycle():
                yield self.dispose_initiators
                yield self.close_initiators
            ctx.effect(lifecycle, 'agents.initiatorLifecycle()')
            self._install_archive_admission(ctx)

    def _install_archive_admission(self, ctx):
        async def activity(request, next_fn):
            agent = self.get(request['sessionId'])
            running = agent is not None and agent.status == 'running'
            rest = await next_fn()
            return [dict(kind='turn')] + list(rest) if running else rest

        def stop(request):
            agent = self.get(request['sessionId'])
            if agent is not None and agent.status == 'running':
                agent.cancel(dict(kind='user'))

        ctx.on('workspace/session-activity', activity)
        ctx.on('workspace/session-stop', stop)

    def _has_lifecycle_ancestor(self, candidate):
        fiber = self._initiator_runtime['ctx'].fiber
        while True:
            if fiber is candidate:return True
            parent = fiber.parent.fiber
            if parent is fiber:return False
            fiber = parent

    def current_initiator(self):
        if self.format_version != 4:return super().current_initiator()
        if self._initiator_state == 'disposed':raise RuntimeError('agent initiator scope is disposed')
        return self._initiator_runtime['value'].get()

    currentInitiator = current_initiator

    def require_initiator(self):
        if self.format_version != 4:return super().require_initiator()
        agent = self.current_initiator()
        if agent is None:raise RuntimeError('no initiating agent is active')
        return agent

    requireInitiator = require_initiator

    def _release_initiator_run(self, run):
        if not run['active']:return
        run['active'] = False
        self._active_initiator_runs -= 1
        if self._active_initiator_runs == 0 and self._initiator_drain is not None:
            self._initiator_drain.set()
            self._initiator_drain = None

    def _run_with_initiator(self, agent, operation, *args, **kwargs):
        if self._initiator_state != 'active':raise RuntimeError('agent initiator scope is disposed')
        runtime = self._initiator_runtime
        run = dict(active=True, parent=runtime['runs'].get())
        self._active_initiator_runs += 1
        run_token = runtime['runs'].set(run);agent_token = runtime['value'].set(agent)
        try:
            try:
                result = operation(*args, **kwargs)
                if inspect.iscoroutine(result):
                    # A Python async call becomes the framework's Promise analogue
                    # here, with its prefix and tail inside the inherited boundary.
                    result = contextvars.copy_context().run(start_coroutine, result)
            except BaseException:
                self._release_initiator_run(run)
                raise
        finally:
            runtime['value'].reset(agent_token);runtime['runs'].reset(run_token)
        future_type = (asyncio.Future, asyncio.futures._PyFuture)
        if isinstance(result, future_type):
            observer = asyncio.Future if isinstance(result, asyncio.Future) else asyncio.futures._PyFuture
            def settled(future):
                try:
                    if not observer.cancelled(future):observer.exception(future)
                finally:self._release_initiator_run(run)
            try:
                # Preserve the exact Future and avoid its overridable observer API.
                observer.add_done_callback(result, settled)
            except Exception:
                self._release_initiator_run(run)
        else:
            self._release_initiator_run(run)
        return result

    def with_initiator(self, agent, operation, *args, **kwargs):
        if self.format_version != 4:return super().with_initiator(agent, operation, *args, **kwargs)
        return self._run_with_initiator(agent, operation, *args, **kwargs)

    withInitiator = with_initiator

    async def with_initiator_async(self, agent, coroutine):
        if self.format_version != 4:return await super().with_initiator_async(agent, coroutine)
        return await self._run_with_initiator(agent, lambda:coroutine)

    def without_initiator(self, operation, *args, **kwargs):
        if self.format_version != 4:return super().without_initiator(operation, *args, **kwargs)
        return self._run_with_initiator(None, operation, *args, **kwargs)

    withoutInitiator = without_initiator

    def close_initiators(self):
        if self.format_version != 4:return super().close_initiators()
        if self._initiator_state == 'active':self._initiator_state = 'closing'

    closeInitiators = close_initiators

    def dispose_initiators(self):
        if self.format_version != 4:return super().dispose_initiators()
        runtime = self._initiator_runtime
        if runtime['disposal'] is None:
            self.close_initiators()
            run = runtime['runs'].get()
            while run is not None:
                self._release_initiator_run(run);run = run['parent']
            async def finish():
                if self._active_initiator_runs != 0:
                    if self._initiator_drain is None:self._initiator_drain = asyncio.Event()
                    await self._initiator_drain.wait()
                self._initiator_state = 'disposed'
            runtime['disposal'] = start_coroutine(finish())
        return runtime['disposal']

    disposeInitiators = dispose_initiators

    async def initialize(self):
        if self.format_version == 4:
            from dsh.core.turn_boundary import TURN_BOUNDARY_DEFINITION
            self._turn_boundary_handle = await self.ctx.get('sessionProjections').register(TURN_BOUNDARY_DEFINITION)

    def turnBoundaryOf(self, session):
        if self.format_version == 4:
            return self._turn_boundary_handle.stateOf(session)
        return self.ctx.get('sessionProjections').stateOf(session,'turnBoundary')

    def _host_context_adapter(self):
        adapter = dict(wire='agentId', wireTypeSymbol='@deepseek-ai/dsh-session/types#SessionId',
                       resolve=lambda sid: self.get(sid).ctx if self.get(sid) is not None else None)
        if self.format_version == 4:adapter['resource'] = 'session'
        return adapter

    def _host_lookup_provider(self):
        provider = super()._host_lookup_provider()
        if self.format_version == 4:provider['resource'] = 'session'
        return provider

    def _factory_request_options(self, request):
        return dict(parent_agent=request.get('parentAgent', request.get('parent_agent')))

    def set_factory(self, factory):
        if self.format_version != 4:return super().set_factory(factory)
        def setup():
            if self._factory is not None:
                raise RuntimeError('an agent factory is already registered')
            self._factory = getattr(factory, symbols.original, None) or factory
            def remove():self._factory = None
            return remove
        return self.ctx.effect(setup, 'agents.setFactory()')

    setFactory = set_factory

    def _require_factory_receiver(self):
        if self._factory is None:
            raise RuntimeError('no agent factory registered (load an agent-loop plugin)')
        return get_traceable(self.ctx, self._factory)

    async def create(self, session_id=None, options=None, meta=None, setup=None, **kwargs):
        if self.format_version != 4:
            return await super().create(session_id, options, meta, setup, **kwargs)
        request = session_id
        if not isinstance(request, dict):
            request = dict(kwargs, sessionId=session_id, agentOptions=options, meta=meta, setup=setup)
        receiver = self._require_factory_receiver()
        result = receiver.createAgent(self.ctx, request)
        return await result if inspect.isawaitable(result) else result

    async def resume(self, resume_session_id, options=None, setup=None, **kwargs):
        if self.format_version != 4:
            return await super().resume(resume_session_id, options, setup, **kwargs)
        request = resume_session_id
        if not isinstance(request, dict):
            request = dict(kwargs, resumeSessionId=resume_session_id, agentOptions=options, setup=setup)
        receiver = self._require_factory_receiver()
        result = receiver.resume(self.ctx, request)
        return await result if inspect.isawaitable(result) else result

    def enter(self, agent, owner=None, creator=None):
        detach = super().enter(agent, owner=owner, creator=creator)
        if self.format_version == 4:
            self._store[agent.id].carrier = agent_carrier(agent)
        return detach

    def _detach_entered(self, entry):
        if self.format_version != 4:return super()._detach_entered(entry)
        entry.detach_requested = False
        if self._store.get(entry.id) is not entry:return
        self._store.pop(entry.id)
        if not entry.announced:return
        class DisposalDispatch(AgentEventDispatch):
            def _warn(dispatch, name, failure, error):
                text = _js_error_to_string(error) if isinstance(error, BaseException) else str(error)
                dispatch.ctx.logger.warn('agent "%s": agent/disposed listener %s: %s' % (entry.id, failure, text))
        DisposalDispatch(self.ctx, entry.agent, entry.carrier).emit('agent/disposed', {})

    def announce(self, agent, source='startup', signal=None):
        if self.format_version != 4:return super().announce(agent)
        async def dispatch():
            entry = self._store.get(agent.id)
            if entry is None or entry.agent is not agent:
                raise RuntimeError('agent "%s" is not live in this registry' % agent.id)
            if entry.announced or entry.announcing:
                raise RuntimeError('agent "%s" was already announced' % entry.id)
            entry.announcing = entry.announced = True
            payload = dict(agent=entry.agent, source=source)
            if signal is not None:payload['signal'] = signal
            try:
                await self.ctx.serial(entry.carrier, 'agent/created', payload)
            finally:
                entry.announcing = False
                if entry.detach_requested:self._detach_entered(entry)
        return start_coroutine(dispatch())

    def register(self, agent):
        if self.format_version != 4:return super().register(agent)
        async def lifecycle():
            yield self.enter(agent)
            await self.announce(agent, 'startup')
        return self.ctx.effect(lifecycle, 'agents.register()')

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
