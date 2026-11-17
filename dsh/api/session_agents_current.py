"""Current Session-addressed Agent activation and model-selection ownership."""
import asyncio
import os
import weakref
from types import SimpleNamespace

from dsh.api.session_agents import selection_state
from dsh.api.session_commands_current import has_subagent_owner, ownership_error
from dsh.core.model_selection import ModelSelection, install_model_selection
from dsh.session.session_query import SessionQueryError
from dsh.typert.remote import RemoteError


class ApiSessionNotFound(RuntimeError):
    pass


class ApiSessionSubagentOwnership(RuntimeError):
    def __init__(self, session_id):
        self.sessionId = session_id
        super().__init__('session "{}" is a subagent session; use subagent delivery'.format(session_id))


class ApiSessionCwdConflict(RuntimeError):
    def __init__(self, session_id, requested, existing):
        self.sessionId, self.requestedCwd, self.existingCwd = session_id, requested, existing
        super().__init__(('session "{}" records no cwd and cannot be adopted for "{}"'.format(session_id, requested)
                          if existing is None else 'session "{}" belongs to "{}", not "{}"'.format(session_id, existing, requested)))


class ApiSessionPresetConflict(RuntimeError):
    def __init__(self, session_id, requested, existing):
        self.sessionId, self.requestedPreset, self.existingPreset = session_id, requested, existing
        super().__init__(('session "{}" records no agent preset and cannot be adopted under "{}"'.format(session_id, requested)
                          if existing is None else 'session "{}" runs agent preset "{}", not "{}"'.format(session_id, existing, requested)))


def selection_dict(value):
    return value.to_dict() if isinstance(value, ModelSelection) else value


def selection_schema(value):
    def selection(entry):
        if entry is None:
            return None
        if not isinstance(entry, dict):
            raise TypeError('model selection must be an object')
        fields = ('provider', 'model', 'reasoningEffort') if 'reasoningEffort' in entry else ('provider', 'model')
        if any(not isinstance(entry.get(key), str) or not entry[key] for key in fields):
            raise TypeError('model selection fields must be nonempty strings')
        return {key: entry[key] for key in fields}
    return dict(lastUsed=selection(value['lastUsed']), pending=selection(value['pending']))


def install_model_selection_projection(ctx):
    return ctx.get('sessionProjections').register(dict(key='modelSelection', stateVersion=2,
        stateSchema=selection_schema, init=lambda *_: dict(lastUsed=None, pending=None), apply=selection_state,
        wire=dict(viewSchema=lambda value: value, view=lambda state: dict(lastUsed=state['lastUsed'], next=state['pending'] or state['lastUsed']))))


async def inspect_api_session(ctx, session_id, signal=None):
    try:
        observed = await ctx.get('sessionQuery').observeSession(session_id, dict(projectionMode='none', **(dict(signal=signal) if signal is not None else {})))
        try:
            if observed.header.cwd is None:
                raise ApiSessionNotFound('session "{}" not found'.format(session_id))
            return dict(meta=observed.header, inheritedEventCount=observed.inheritedEventCount, events=list(observed.events))
        finally:
            observed.dispose()
    except SessionQueryError as error:
        if error.code == 'SESSION_QUERY_SESSION_NOT_FOUND':
            raise ApiSessionNotFound('session "{}" not found'.format(session_id)) from None
        raise


class InstalledSelection:
    def __init__(self, owner, agent, pending):
        self.owner, self.agent, self.picked, self.assembled = owner, agent, pending, None

    @property
    def current(self):
        value = self.picked
        if value is None:
            header = self.agent.session.requestHeader()
            if header is None:
                value = self.owner.ctx.get('agentDefaultModel').currentSelection()
            else:
                value = {key: header['config'][key] for key in ('provider', 'model', 'reasoningEffort') if key in header['config']}
                if header.get('adapterDefaults', {}).get('reasoningEffort') is True:
                    value.pop('reasoningEffort', None)
        return ModelSelection(value['provider'], value['model'], value.get('reasoningEffort'))

    @current.setter
    def current(self, value):
        self.picked = selection_dict(value)

    def consume(self, provider, model, reasoning_effort=None):
        if self.picked is None or any(self.picked.get(key) != value for key, value in
            [('provider', provider), ('model', model), ('reasoningEffort', reasoning_effort)]):
            return False
        self.picked = None
        return True


class CurrentSessionAgents:
    def __init__(self, ctx):
        self.ctx, self.resumes, self.creations = ctx, {}, {}
        self.selections, self.admissions = weakref.WeakKeyDictionary(), weakref.WeakKeyDictionary()
        async def lookup(sid):
            found = await self.resolveAgent(sid)
            if 'error' in found:
                raise found['error']
            return found['agent']
        async def session(sid):
            return (await lookup(sid)).session
        async def context(sid):
            return (await lookup(sid)).ctx
        typert = ctx.get('typert')
        typert.lookups.configure('agent', lookup)
        typert.lookups.configure('session', session)
        typert.contexts.configureHost('agent', context)

    def _live(self, sid):
        agent = self.ctx.get('agents').get(sid)
        if agent is None:
            return None
        return dict(error=ownership_error(sid)) if has_subagent_owner(self.ctx, agent.session, agent) else dict(agent=agent)

    @staticmethod
    def _forget(mapping, key, task):
        if mapping.get(key) is task:
            mapping.pop(key, None)

    async def resolveAgent(self, sid):
        return await self._resolve(sid)

    async def resolveObservedAgent(self, observation):
        return await self._resolve(observation.header.id, observation)

    async def _resolve(self, sid, observation=None):
        live = self._live(sid)
        if live is not None:
            return live
        attached = self.ctx.get('sessions').get(sid)
        if attached is not None and has_subagent_owner(self.ctx, attached):
            return dict(error=ownership_error(sid))
        if sid not in self.resumes:
            task = asyncio.ensure_future(self._resume(sid, observation))
            self.resumes[sid] = task
            task.add_done_callback(lambda done: self._forget(self.resumes, sid, done))
        try:
            return dict(agent=await asyncio.shield(self.resumes[sid]))
        except Exception as error:
            if isinstance(error, ApiSessionNotFound):
                return dict(error=RemoteError('session/not-found', str(error), dict(sessionId=sid)))
            if isinstance(error, ApiSessionSubagentOwnership):
                return dict(error=ownership_error(error.sessionId))
            raced = self._live(sid)
            if raced is not None:
                return raced
            attached = self.ctx.get('sessions').get(sid)
            if attached is not None and has_subagent_owner(self.ctx, attached):
                return dict(error=ownership_error(sid))
            detail = getattr(error, 'name', 'Error') + ': ' + getattr(error, 'message', str(error))
            return dict(error=RemoteError('gateway/internal', 'resume failed for session "{}": {}'.format(sid, detail), {}))

    async def _resume(self, sid, supplied):
        if supplied is not None:
            return await self._resume_observed(sid, supplied)
        try:
            observed = await self.ctx.get('sessionQuery').observeSession(sid)
            try:
                return await self._resume_observed(sid, observed)
            finally:
                observed.dispose()
        except SessionQueryError as error:
            if error.code == 'SESSION_QUERY_SESSION_NOT_FOUND':
                raise ApiSessionNotFound('session "{}" not found'.format(sid)) from None
            raise

    async def _resume_observed(self, sid, observed):
        if observed.header.id != sid or observed.header.cwd is None:
            raise ApiSessionNotFound('session "{}" not found'.format(sid))
        if has_subagent_owner(self.ctx, SimpleNamespace(header=observed.header)):
            raise ApiSessionSubagentOwnership(sid)
        composition = await self.composeAgent(self.presetForObservation(observed))
        published, live = self.ctx.get('sessions').get(sid), self.ctx.get('agents').get(sid)
        if published is not None and has_subagent_owner(self.ctx, published, live):
            raise ApiSessionSubagentOwnership(sid)
        return (await self.ctx.get('agents').resume(dict(resumeSessionId=sid, agentOptions=self.agent_options(), setup=composition['setup']))).agent

    async def ensureSession(self, sid, cwd, check_persisted_identity, preset_id=None):
        if sid not in self.creations:
            task = asyncio.ensure_future(self._create_or_race(sid, cwd, check_persisted_identity, preset_id))
            self.creations[sid] = task
            task.add_done_callback(lambda done: self._forget(self.creations, sid, done))
        agent = await asyncio.shield(self.creations[sid])
        if has_subagent_owner(self.ctx, agent.session, agent):
            raise ApiSessionSubagentOwnership(sid)
        self.assert_preset(sid, preset_id, self.presetForSession(agent.session))
        if agent.session.header.cwd != cwd:
            raise ApiSessionCwdConflict(sid, cwd, agent.session.header.cwd)
        return agent

    async def _create_or_race(self, sid, cwd, check_persisted, preset_id):
        try:
            return await self._create_or_adopt(sid, cwd, check_persisted, preset_id)
        except Exception:
            live = self.ctx.get('agents').get(sid)
            if live is not None:
                if has_subagent_owner(self.ctx, live.session, live):
                    raise ApiSessionSubagentOwnership(sid) from None
                return live
            attached = self.ctx.get('sessions').get(sid)
            if attached is not None and has_subagent_owner(self.ctx, attached):
                raise ApiSessionSubagentOwnership(sid) from None
            raise

    async def _create_or_adopt(self, sid, cwd, check_persisted, preset_id):
        attached, live = self.ctx.get('sessions').get(sid), self.ctx.get('agents').get(sid)
        if attached is not None and has_subagent_owner(self.ctx, attached, live):
            raise ApiSessionSubagentOwnership(sid)
        if live is not None:
            return live
        if check_persisted:
            try:
                observed = await self.ctx.get('sessionQuery').observeSession(sid)
                try:
                    if has_subagent_owner(self.ctx, SimpleNamespace(header=observed.header)):
                        raise ApiSessionSubagentOwnership(sid)
                    if observed.header.cwd != cwd:
                        raise ApiSessionCwdConflict(sid, cwd, observed.header.cwd)
                    stored_preset = self.presetForObservation(observed)
                    self.assert_preset(sid, preset_id, stored_preset)
                    composition = await self.composeAgent(stored_preset)
                    return (await self.ctx.get('agents').resume(dict(resumeSessionId=sid, agentOptions=self.agent_options(), setup=composition['setup']))).agent
                finally:
                    observed.dispose()
            except SessionQueryError as error:
                if error.code != 'SESSION_QUERY_SESSION_NOT_FOUND':
                    raise
        from dsh.attachment.immutable_current import disk
        try:
            await disk(os.makedirs, cwd, 0o777, True)
        except Exception as error:
            raise RuntimeError('failed to ensure project directory "{}": Error: {}'.format(cwd, error)) from error
        composition = await self.composeAgent(preset_id)
        meta = dict(cwd=cwd)
        if 'agentPreset' in composition:
            meta['agentPreset'] = composition['agentPreset']
        return (await self.ctx.get('agents').create(dict(sessionId=sid, agentOptions=self.agent_options(), meta=meta, setup=composition['setup']))).agent

    def selectionFor(self, agent):
        if agent not in self.selections:
            state = self.ctx.get('sessionProjections').stateOf(agent.session, 'modelSelection')
            if state is None:
                raise RuntimeError('api-session: required modelSelection projection is not registered')
            selection = InstalledSelection(self, agent, state['pending'])
            install_model_selection(agent.ctx, selection)
            self.selections[agent] = selection
        return self.selections[agent]

    def selectForNextRequest(self, agent, selection):
        value = selection_dict(selection)
        agent.session.append('model/selection', value)
        self.selectionFor(agent).current = value

    def consumeSelection(self, agent, provider, model, reasoning_effort=None):
        selection = self.selections.get(agent)
        return selection.consume(provider, model, reasoning_effort) if selection is not None else False

    def presetForSession(self, session):
        return self.ctx.get('sessionProjections').stateOf(session, 'agentPreset')

    @staticmethod
    def presetForObservation(observation):
        if observation.projections is None:
            raise RuntimeError('api-session: Agent activation requires a projected Session observation')
        return observation.projections['values'].get('agentPreset')

    async def serializeImageAdmission(self, agent, operation):
        if agent not in self.admissions:
            self.admissions[agent] = asyncio.Lock()
        async with self.admissions[agent]:
            return await operation()

    async def composeAgent(self, preset_id):
        presets = self.ctx.get('agentPresets')
        definition = await presets.resolve(preset_id) if presets is not None else None
        resolved = (definition['id'] if isinstance(definition, dict) else definition.id) if definition is not None else None
        async def setup(agent_ctx, agent):
            self.selectionFor(agent)
            if presets is not None:
                await presets.mount(agent_ctx, resolved)
        return dict(setup=setup, **(dict(agentPreset=resolved) if resolved is not None else {}))

    def agent_options(self):
        value = self.ctx.get('agentDefaultModel').currentSelection()
        return dict(provider=value['provider'], model=value['model'])

    @staticmethod
    def assert_preset(sid, requested, existing):
        if requested is not None and requested != existing:
            raise ApiSessionPresetConflict(sid, requested, existing)
