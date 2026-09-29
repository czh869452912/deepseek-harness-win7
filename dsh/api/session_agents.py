"""Session-addressed Agent activation and durable model selection policy."""
import asyncio
import os
import weakref

from dsh.api.settings import failure
from dsh.core.model_selection import ModelSelection, install_model_selection
from dsh.session.session_query import SessionQueryError
from dsh.typert.remote import TypertLookupFailure


def selection_state(state, event):
    if event['type'] == 'model/selection':
        return dict(state, pending=event['data']) if state['pending'] != event['data'] else state
    if event['type'] != 'request/header':
        return state
    config = event['data']['header']['config']
    used = {key: config[key] for key in ('provider', 'model', 'reasoningEffort') if key in config}
    pending = None if state['pending'] == used else state['pending']
    return state if state['lastUsed'] == used and pending is state['pending'] else dict(lastUsed=used, pending=pending)


class Selection:
    def __init__(self, owner, agent):
        self.owner, self.agent, self.assembled = owner, agent, None
        self.picked = owner.ctx.get('sessionProjections').stateOf(agent.session, 'modelSelection')['pending']

    @property
    def current(self):
        value = self.picked
        if value is None:
            header = self.agent.session.requestHeader()
            if header is None:
                value = self.owner.ctx.get('agentDefaultModel').currentSelection()
            else:
                value = {key: header['config'][key] for key in ('provider', 'model', 'reasoningEffort') if key in header['config']}
                if header.get('adapterDefaults', {}).get('reasoningEffort'):
                    value.pop('reasoningEffort', None)
        return ModelSelection(value['provider'], value['model'], value.get('reasoningEffort'))


class SessionAgents:
    def __init__(self, ctx):
        self.ctx, self.resumes, self.creations = ctx, {}, {}
        self.selections, self.admissions = weakref.WeakKeyDictionary(), weakref.WeakKeyDictionary()
        registry = ctx.get('sessionProjections')
        registry.register(dict(key='modelSelection', stateVersion=2, stateSchema=lambda value: value,
                               init=lambda _: dict(lastUsed=None, pending=None), apply=selection_state,
                               wire=dict(viewSchema=lambda value: value, view=lambda state: dict(lastUsed=state['lastUsed'], next=state['pending'] or state['lastUsed']))))
        async def lookup(sid):
            try:
                return await self.resolve(sid)
            except Exception as error:
                if hasattr(error, 'failure'):
                    raise TypertLookupFailure(error.failure) from error
                raise
        async def session(sid):
            return (await lookup(sid)).session
        async def context(sid):
            return (await lookup(sid)).ctx
        typert = ctx.get('typert')
        typert.lookups.configure('agent', lookup)
        typert.lookups.configure('session', session)
        typert.contexts.configureHost('agent', context)

    def check_owner(self, header, agent=None):
        parent = self.ctx.get('agents').get(header.parentSession) if header.parentSession else None
        if header.origin == 'subagent' or parent is not None and agent is not None and self.ctx.get('agents').isOwnedBy(agent.id, parent):
            raise failure('agent-busy', 'session "%s" is owned by subagent routing' % header.id,
                          {'reason': 'use subagent delivery for this child session'})

    def preset(self, session):
        return self.ctx.get('sessionProjections').stateOf(session, 'agentPreset')

    def selection(self, agent):
        if agent not in self.selections:
            value = self.selections[agent] = Selection(self, agent)
            install_model_selection(agent.ctx, value)
        return self.selections[agent]

    def admission(self, agent):
        if agent not in self.admissions:
            self.admissions[agent] = asyncio.Lock()
        return self.admissions[agent]

    async def compose(self, preset):
        presets = self.ctx.get('agentPresets')
        resolved = (await presets.resolve(preset)).id if presets is not None else None
        async def setup(ctx):
            self.selection(ctx.agent)
            if presets is not None:
                await presets.mount(ctx, resolved)
        return resolved, setup

    def options(self):
        selection = self.ctx.get('agentDefaultModel').currentSelection()
        return {key: selection[key] for key in ('provider', 'model')}

    async def resolve(self, sid, observation=None):
        live = self.ctx.get('agents').get(sid)
        if live is not None:
            self.check_owner(live.session.header, live)
            return live
        attached = self.ctx.get('sessions').get(sid)
        if attached is not None:
            self.check_owner(attached.header)
        if sid not in self.resumes:
            async def resume():
                source = observation.retain() if observation is not None else None
                try:
                    if source is None:
                        source = await self.ctx.get('sessionQuery').observeSession(sid)
                    if source.header.cwd is None:
                        raise failure('session-not-found', 'session "%s" not found' % sid, {'sessionId': sid})
                    self.check_owner(source.header)
                    _, setup = await self.compose(source.projections['values'].get('agentPreset'))
                    return (await self.ctx.get('agents').resume(dict(resumeSessionId=sid, agentOptions=self.options(), setup=setup))).agent
                except SessionQueryError as error:
                    if error.code == 'SESSION_QUERY_SESSION_NOT_FOUND':
                        raise failure('session-not-found', 'session "%s" not found' % sid, {'sessionId': sid}) from error
                    raise
                finally:
                    if source is not None:
                        source.dispose()
            task = self.resumes[sid] = asyncio.create_task(resume())
            task.add_done_callback(lambda done: self.resumes.pop(sid, None))
        return await asyncio.shield(self.resumes[sid])

    async def ensure(self, sid, cwd, explicit, preset):
        if sid not in self.creations:
            async def create():
                agent = self.ctx.get('agents').get(sid)
                if agent is not None:
                    return agent
                attached = self.ctx.get('sessions').get(sid)
                if attached is not None:
                    self.check_owner(attached.header)
                if explicit:
                    observed = None
                    try:
                        observed = await self.ctx.get('sessionQuery').observeSession(sid)
                        self.check_owner(observed.header)
                        self.check_identity(sid, cwd, preset, observed.header.cwd, observed.projections['values'].get('agentPreset'))
                        return await self.resolve(sid, observed)
                    except SessionQueryError as error:
                        if error.code != 'SESSION_QUERY_SESSION_NOT_FOUND':
                            raise
                    finally:
                        if observed is not None:
                            observed.dispose()
                os.makedirs(cwd, exist_ok=True)
                resolved, setup = await self.compose(preset)
                meta = dict(cwd=cwd)
                if resolved is not None:
                    meta['agentPreset'] = resolved
                return (await self.ctx.get('agents').create(dict(sessionId=sid, meta=meta, agentOptions=self.options(), setup=setup))).agent
            task = self.creations[sid] = asyncio.create_task(create())
            task.add_done_callback(lambda done: self.creations.pop(sid, None))
        agent = await asyncio.shield(self.creations[sid])
        self.check_owner(agent.session.header, agent)
        self.check_identity(sid, cwd, preset, agent.session.header.cwd, self.preset(agent.session))
        return agent

    @staticmethod
    def check_identity(sid, cwd, preset, stored_cwd, stored_preset):
        if preset is not None and preset != stored_preset:
            details = dict(sessionId=sid, requestedPreset=preset)
            if stored_preset is not None:
                details['existingPreset'] = stored_preset
            raise failure('agent-preset-conflict', 'session "%s" uses another agent preset' % sid, details)
        if cwd != stored_cwd:
            details = dict(sessionId=sid, requestedCwd=cwd)
            if stored_cwd is not None:
                details['existingCwd'] = stored_cwd
            raise failure('session-conflict', 'session "%s" belongs to another cwd' % sid, details)
