"""Current Session Remote assembly over explicit Agent and v3 Session capabilities."""
import asyncio
import os
import socket

from dsh.api.session_agents_current import CurrentSessionAgents, inspect_api_session, install_model_selection_projection
from dsh.api.session_commands_current import CurrentSessionCommands
from dsh.api.session_control_current import CurrentSessionControl
from dsh.api.session_history_current import CurrentSessionHistory
from dsh.api.session_list_current import CurrentSessionList
from dsh.api.session_media_current import CurrentSessionMediaReferences
from dsh.api.session_catalogs_current import CurrentSessionSkillCatalog, SessionFileReferences
from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import js_to_string
from dsh.host.native_command_current import can_open_native_path, native_file_manager, open_native_path, reveal_native_path
from dsh.llm.error import error_chain
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService
from dsh.api.session_resource import register_session_resource


async def build_model_catalog(ctx, default_selection=None):
    default_selection = ctx.get('agentDefaultModel').currentSelection() if default_selection is None else default_selection
    llm, providers = ctx.get('llm'), ctx.get('llm').listProviders()
    async def group(provider):
        try:
            async def entry(model):
                resolved = await llm.resolveModelInfo(provider['id'], model['id'])
                value = {key: model[key] for key in ('id', 'name', 'description') if key in model}
                if 'reasoning' in resolved:
                    reasoning = resolved['reasoning']
                    value['reasoning'] = dict(efforts=[{key: effort[key] for key in ('id', 'name', 'description') if key in effort} for effort in reasoning['efforts']],
                        **(dict(defaultEffort=reasoning['defaultEffort']) if 'defaultEffort' in reasoning else {}))
                return value
            entries = await asyncio.gather(*(entry(model) for model in await llm.listModels(provider['id'])))
            return True, dict(id=provider['id'], name=provider['name'], models=entries)
        except Exception as error:
            message = js_to_string(error.value) if isinstance(error, ThrownValueError) else getattr(error, 'message', str(error))
            return False, dict(id=provider['id'], name=provider['name'], message=message)
    rows = await asyncio.gather(*(group(provider) for provider in providers))
    return dict(default=dict(default_selection), routableProviders=[provider['id'] for provider in providers],
        groups=[value for success, value in rows if success and value['models']], failures=[value for success, value in rows if not success])


class CurrentSessionController(TypertRemoteService):
    control_class = CurrentSessionControl
    commands_class = CurrentSessionCommands
    inject = ['agentDefaultModel', 'agents', 'attachments', 'fileUploads', 'llm', 'sessions', 'sessionProjections', 'sessionQuery', 'typert', 'workspaceRegistry']

    def __init__(self, ctx, config=None, internals=None):
        super().__init__(ctx, 'sessionController', dict(namespace='session'))
        config, internals = config or {}, internals or {}
        register_session_resource(ctx)
        install_model_selection_projection(ctx)
        self.agents, self.promotions = CurrentSessionAgents(ctx), set()
        self.commands = self.commands_class(ctx, self.agents, os.getcwd())
        async def resolve(sid):
            found = await self.agents.resolveAgent(sid)
            if 'error' in found:
                raise found['error']
            return found['agent']
        ctx.effect(lambda: ctx.get('fileUploads').registerAgentResolver(resolve), 'session-controller: file-upload Agent resolver')
        self.control_state = self.control_class(ctx)
        ctx.effect(lambda: self.drain, 'session-controller.promotions')
        self.history = CurrentSessionHistory(ctx, self.promote)
        self.list_state = CurrentSessionList(ctx)
        self.open_path, self.reveal_path = internals.get('openPath', open_native_path), internals.get('revealPath', reveal_native_path)
        self.can_open = internals.get('canOpenPath', lambda: config['nativeOpen'] if 'nativeOpen' in config else 'openPath' in internals or can_open_native_path())
        ctx.plugin(SessionFileReferences); ctx.plugin(CurrentSessionMediaReferences); ctx.plugin(CurrentSessionSkillCatalog)
        ctx.on('session/created', lambda session: ctx.emit('api-session/added', self.list_state.summaryFor(session)))
        ctx.on('session/disposed', lambda session: ctx.emit('api-session/removed', session.id))
        ctx.on('agent/status', lambda payload: ctx.emit('api-session/status', payload['agent'].id, payload['status'] == 'running'))
        ctx.on('agent/error', lambda payload: ctx.emit('api-session/error', payload['agent'].id, error_chain(payload['error'])))
        ctx.on('session/event', self.event)

    def event(self, session, event):
        if event['type'] == 'request/header':
            agent = self.ctx.get('agents').get(session.id)
            if agent is not None and agent.session is session:
                config = event['data']['header']['config']
                self.agents.consumeSelection(agent, config['provider'], config['model'], config.get('reasoningEffort'))
        if event['type'] == 'user/message' and event['data']['source']['kind'] == 'user':
            self.ctx.emit('api-session/activity', session.id, event['time'])

    def promote(self, observation):
        sid = observation.header.id
        async def activate():
            try:
                try:
                    found = await self.agents.resolveObservedAgent(observation)
                    if 'error' in found:
                        self.ctx.emit('api-session/error', sid, found['error'].message)
                finally:
                    observation.dispose()
            except Exception as error:
                self.ctx.logger.error('session-controller: background activation for "{}" failed: {}'.format(sid, error_chain(error)))
        task = asyncio.ensure_future(activate())
        self.promotions.add(task)
        task.add_done_callback(self.promotions.discard)

    async def drain(self):
        await asyncio.gather(*list(self.promotions), return_exceptions=True)

    async def resolveAgent(self, sid):
        return await self.agents.resolveAgent(sid)

    async def inspect(self, sid, signal=None):
        attached = self.ctx.get('sessions').get(sid)
        if attached is not None:
            return dict(meta=attached.header, inheritedEventCount=attached.inheritedEventCount, events=attached.snapshotEvents())
        return await inspect_api_session(self.ctx, sid, signal)

    @Remote
    async def list(self, request, signal):
        return dict(items=await self.list_state.list(signal))

    @Remote
    async def search(self, request, signal):
        return await self.list_state.search(request['query'], signal)

    @Remote
    async def create(self, request):
        return await self.commands.create(request)

    @Remote
    async def selectModel(self, request):
        return await self.commands.selectModel(request)

    @Remote
    async def modelCatalog(self):
        return await build_model_catalog(self.ctx)

    @Remote
    def canOpenWorkspacePath(self):
        return self.can_open()

    def workspaceDesktop(self):
        manager = native_file_manager()
        return dict(name=socket.gethostname(), available=manager is not None and self.can_open(), fileManager=manager)

    @Remote
    async def openWorkspacePath(self, request, signal):
        if not request['path']:
            raise RemoteError('gateway/bad-request', 'session.openWorkspacePath requires a non-empty path', {})
        signal.throwIfAborted()
        try:
            await (self.reveal_path if request.get('action') == 'reveal' else self.open_path)(request['path'], signal)
            return dict(opened=True)
        except Exception as error:
            if signal.aborted:
                raise RemoteError('gateway/cancelled', 'path open was aborted', {}) from None
            message = js_to_string(error.value) if isinstance(error, ThrownValueError) else getattr(error, 'message', str(error))
            raise RemoteError('gateway/internal', 'path open failed: ' + message, {}) from None

    @Remote
    async def rename(self, request):
        return await self.commands.rename(request)

    @Remote
    async def fork(self, request):
        return await self.commands.fork(request)

    @Remote
    async def prompt(self, request, signal):
        signal.throwIfAborted()
        return await self.commands.prompt(request)

    @Remote
    async def attachment(self, request):
        return await self.commands.attachment(request)

    @Remote
    def updateQueue(self, request):
        return self.commands.updateQueue(request)

    @Remote
    def cancel(self, request):
        return self.commands.cancel(request)

    @Remote
    async def page(self, request, signal):
        return await self.history.page(request, signal)

    @Remote(dict(mode='stream'))
    def follow(self, request, signal):
        return self.history.follow(request, signal)

    @Remote(dict(mode='stream'))
    def control(self, signal):
        return self.control_state.control(signal)
