"""Ordinary v4 Session activation, ordered blank reuse and core-owned models."""
import asyncio
import os
import uuid

from dsh.api.session_agents_current import (
    CurrentSessionAgents, ApiSessionCwdConflict, ApiSessionPresetConflict,
    ApiSessionSubagentOwnership, ApiSessionNotFound,
)
from dsh.api.session_commands_current import ownership_error, error_text
from dsh.attachment.immutable_current import disk
from dsh.core.model_selection import install_model_selection
from dsh.session.session_query import SessionQueryError
from dsh.typert.remote import remote_error_of, RemoteError


class DefaultModelOptions:
    """Read unrecorded choices from the live deployment default each time."""
    def __init__(self, defaults):
        self.defaults = defaults

    @property
    def provider(self):
        return self.defaults.currentSelection()['provider']

    @property
    def model(self):
        return self.defaults.currentSelection()['model']

    @property
    def reasoningEffort(self):
        return self.defaults.currentSelection().get('reasoningEffort')

    maxTokens = None

    def to_dict(self):
        return dict(self.defaults.currentSelection())


class StartedSinceObserved(RuntimeError):
    pass


class AuthorizedSessionAgents(CurrentSessionAgents):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.claims = {}

    def _live(self, sid):
        agent = self.ctx.get('agents').get(sid)
        if agent is None:
            return None
        return dict(error=ownership_error(sid)) if agent.session.header.origin == 'subagent' else dict(agent=agent)

    async def _resolve(self, sid, observation=None):
        live = self._live(sid)
        if live is not None:
            return live
        attached = self.ctx.get('sessions').get(sid)
        if attached is not None and attached.header.origin == 'subagent':
            return dict(error=ownership_error(sid))
        if sid not in self.resumes:
            task = asyncio.ensure_future(self._resume(sid, observation))
            self.resumes[sid] = task
            def finished(done):
                self._forget(self.resumes, sid, done)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
        task = self.resumes[sid]
        try:
            agent = await asyncio.shield(task)
            return self._live(sid) or dict(agent=agent)
        except Exception as error:
            if isinstance(error, ApiSessionNotFound):
                return dict(error=RemoteError('session/not-found', str(error), dict(sessionId=sid)))
            if isinstance(error, ApiSessionSubagentOwnership):
                return dict(error=ownership_error(error.sessionId))
            raced = self._live(sid)
            if raced is not None:
                return raced
            attached = self.ctx.get('sessions').get(sid)
            if attached is not None and attached.header.origin == 'subagent':
                return dict(error=ownership_error(sid))
            if getattr(error, 'name', type(error).__name__) == 'SessionAlreadyOwnedError':
                return dict(error=RemoteError('session/writer-held', str(error), dict(sessionId=sid)))
            return dict(error=RemoteError('gateway/internal', 'resume failed for session "{}": {}'.format(sid, error_text(error)), {}))

    def presetForSession(self, session):
        presets = self.ctx.get('agentPresets')
        return presets.presetForSession(session) if presets is not None else None

    async def _resume_observed(self, sid, observed):
        if observed.header.id != sid or observed.header.cwd is None:
            raise ApiSessionNotFound('session "{}" not found'.format(sid))
        if observed.header.origin == 'subagent':
            raise ApiSessionSubagentOwnership(sid)
        composition = await self.composeAgent(self.presetForObservation(observed))
        published = self.ctx.get('sessions').get(sid)
        if published is not None and published.header.origin == 'subagent':
            raise ApiSessionSubagentOwnership(sid)
        return (await self.ctx.get('agents').resume(dict(resumeSessionId=sid, agentOptions=self.agent_options(), setup=composition['setup']))).agent

    async def composeAgent(self, preset_id):
        presets = self.ctx.get('agentPresets')
        resolved = (await presets.resolve(preset_id))['id'] if presets is not None else None
        async def setup(agent_ctx, agent):
            install_model_selection(agent_ctx)
            if presets is not None:
                return await presets.mount(agent_ctx, resolved)
        return dict(setup=setup, **(dict(agentPreset=resolved) if resolved is not None else {}))

    def agent_options(self):
        return DefaultModelOptions(self.ctx.get('agentDefaultModel'))

    async def createSession(self, request):
        sid = request.get('sessionId')
        if sid is None:
            agent = await self._mint(request['cwd'], await self.composeAgent(request.get('agentPreset')))
        else:
            previous = self.claims.get(sid)
            async def claim():
                if previous is not None:
                    try:
                        await asyncio.shield(previous)
                    except (Exception, asyncio.CancelledError):
                        pass
                return self._created(await self._claim(sid, request))
            task = asyncio.ensure_future(claim())
            self.claims[sid] = task
            def finished(done):
                self._forget(self.claims, sid, done)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(finished)
            return await asyncio.shield(task)
        return self._created(agent)

    def _created(self, agent):
        return dict(agent=agent, agentPreset=self.presetForSession(agent.session))

    def _blank(self, session):
        boundary = self.ctx.get('agents').turnBoundaryOf(session)
        return boundary['openTurnStartSeq'] is None and boundary['lastTurn'] == 0

    def _assert_applicable(self, sid, preset):
        if preset is not None and self.ctx.get('agentPresets') is None:
            raise ApiSessionPresetConflict(sid, preset, None)

    async def _reuse_live(self, live, request, composition):
        if not request['reusable'](live.id) or not self._blank(live.session):
            return None
        self._assert_applicable(live.id, request.get('agentPreset'))
        presets = self.ctx.get('agentPresets')
        target = composition.get('agentPreset')
        if presets is None or target is None or target == self.presetForSession(live.session):
            return live
        try:
            await presets.select(live, target)
        except Exception as error:
            remote = remote_error_of(error)
            if remote is None or remote['code'] != 'agent-preset/locked':
                raise
            return None
        return live

    async def _claim(self, sid, request):
        attached, live = self.ctx.get('sessions').get(sid), self.ctx.get('agents').get(sid)
        if attached is not None and attached.header.origin == 'subagent':
            raise ApiSessionSubagentOwnership(sid)
        if live is not None:
            if live.session.header.cwd != request['cwd']:
                raise ApiSessionCwdConflict(sid, request['cwd'], live.session.header.cwd)
            composition = await self.composeAgent(request.get('agentPreset'))
            reused = await self._reuse_live(live, request, composition)
            return reused if reused is not None else await self._mint(request['cwd'], composition)
        try:
            observed = await self.ctx.get('sessionQuery').observeSession(sid)
        except SessionQueryError as error:
            if error.code != 'SESSION_QUERY_SESSION_NOT_FOUND':
                raise
            return await self._create_agent(sid, request['cwd'], await self.composeAgent(request.get('agentPreset')))
        try:
            if observed.header.origin == 'subagent':
                raise ApiSessionSubagentOwnership(sid)
            if observed.header.cwd != request['cwd']:
                raise ApiSessionCwdConflict(sid, request['cwd'], observed.header.cwd)
            reusable = request['reusable'](sid) and not any(event['type'] == 'turn/start' for event in observed.events)
        finally:
            observed.dispose()
        composition = await self.composeAgent(request.get('agentPreset'))
        if not reusable:
            return await self._mint(request['cwd'], composition)
        self._assert_applicable(sid, request.get('agentPreset'))
        async def setup(agent_ctx, agent):
            if not self._blank(agent.session):
                raise StartedSinceObserved()
            commit = await composition['setup'](agent_ctx, agent)
            target = composition.get('agentPreset')
            if target is not None and self.presetForSession(agent.session) != target:
                agent.session.append('agent-preset/selected', dict(agentPreset=target))
            return commit
        try:
            return (await self.ctx.get('agents').resume(dict(resumeSessionId=sid, agentOptions=self.agent_options(), setup=setup))).agent
        except Exception as error:
            if isinstance(error, StartedSinceObserved):
                return await self._mint(request['cwd'], composition)
            if getattr(error, 'name', type(error).__name__) != 'SessionAlreadyOwnedError':
                raise
            return (await self._mint(request['cwd'], composition) if self.ctx.get('agents').get(sid) is None
                    else await self._claim(sid, request))

    async def _mint(self, cwd, composition):
        return await self._create_agent('session-' + str(uuid.uuid4()), cwd, composition)

    async def _create_agent(self, sid, cwd, composition):
        try:
            await disk(os.makedirs, cwd, 0o777, True)
        except Exception as error:
            raise RuntimeError('failed to ensure project directory "{}": Error: {}'.format(cwd, error)) from error
        meta = dict(cwd=cwd)
        if 'agentPreset' in composition:
            meta['agentPreset'] = composition['agentPreset']
        return (await self.ctx.get('agents').create(dict(sessionId=sid, agentOptions=self.agent_options(),
                    meta=meta, setup=composition['setup']))).agent
