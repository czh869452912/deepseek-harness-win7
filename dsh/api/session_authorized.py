"""Resource-filtered Session Remote reads and v4 projection control frames."""
import os

from dsh.api.session_current import CurrentSessionController
from dsh.api.session_control_current import CurrentSessionControl
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService
from dsh.typert.principal import principal_of
from dsh.core.session.json import UNDEFINED
from dsh.api.session_commands_authorized import AuthorizedSessionCommands
from dsh.api.session_commands_current import has_prompt_content
from dsh.util_time import canonical_client_time_zone
from dsh.api.session_agents_authorized import AuthorizedSessionAgents
from dsh.api.session_history_authorized import SessionHistoryController
from dsh.api.session_web_authorized import SessionWebController
from dsh.api.session_state_authorized import SessionStateController
from dsh.api.session_list_authorized import AuthorizedSessionList
from dsh.api.archived_session_gate import ArchivedSessionGate
from dsh.api.session_resource import register_session_resource
from dsh.api.session_catalogs_current import SessionFileReferences
from dsh.api.session_catalogs_authorized import AuthorizedSessionSkillCatalog
from dsh.api.session_media_current import CurrentSessionMediaReferences
from dsh.cordis.schema import Schema
from dsh.host.native_command_current import can_open_native_path, open_native_associated_path, reveal_native_path
from dsh.llm.error import error_chain
from dsh.host.file_applications import native_file_applications, open_native_file_application


class ProjectionSessionControl(CurrentSessionControl):
    def __init__(self, ctx):
        self.ctx, self.streams = ctx, set()
        def changed(session, changes, seq):
            self.broadcast(dict(type='projection', sessionId=session.id, seq=seq, changes=changes))
        ctx.get('sessionProjections').onEventChanged(changed)
        ctx.effect(lambda: self.close, 'session-controller.control')

    def baseline(self):
        return dict(projections={session.id:self.ctx.get('sessionProjections').snapshot(session)
                                 for session in self.ctx.get('sessions').list()})


class AuthorizedSessionController(CurrentSessionController):
    Config = Schema.object(dict(nativeOpen=Schema.boolean(), listWorkSliceMs=Schema.natural().min(1).default(16)))
    inject = ['agentDefaultModel', 'agents', 'attachments', 'fileUploads', 'fs', 'llm', 'remoteAccess',
              'sessions', 'sessionProjections', 'sessionQuery', 'typert', 'typertGateway', 'workspaceRegistry']
    control_class = ProjectionSessionControl
    commands_class = AuthorizedSessionCommands
    agents_class = AuthorizedSessionAgents
    model_projection = staticmethod(lambda ctx: None)

    def __init__(self, ctx, config=None, internals=None):
        TypertRemoteService.__init__(self, ctx, 'sessionController', dict(namespace='session'))
        config, internals = self.Config(config or {}), internals or {}
        self.list_work_slice_ms = config['listWorkSliceMs']
        self.open_path, self.reveal_path = internals.get('openPath', open_native_associated_path), internals.get('revealPath', reveal_native_path)
        self.file_applications = internals.get('fileApplications', native_file_applications)
        self.open_file_application = internals.get('openFileApplication', open_native_file_application)
        self.can_open = internals.get('canOpenPath', lambda: config['nativeOpen'] if 'nativeOpen' in config else 'openPath' in internals or can_open_native_path())

    async def init(self):
        ctx = self.ctx
        register_session_resource(ctx)
        self.agents, self.promotions = self.agents_class(ctx), set()
        self.commands = self.commands_class(ctx, self.agents, os.getcwd())
        async def resolve(identity):
            found = await self.agents.resolveAgent(identity)
            if 'error' in found:
                raise found['error']
            return found['agent']
        ctx.effect(lambda: ctx.get('fileUploads').registerAgentResolver(resolve), 'session-controller: file-upload Agent resolver')
        self.control_state = self.control_class(ctx)
        ctx.effect(lambda: self.drain, 'session-controller.promotions')
        # Capture Assistant openings before either awaited initialization can yield.
        self.history_reads = SessionHistoryController(ctx)
        self.state_controller = SessionStateController(ctx, self.history_reads)
        self.web_controller = SessionWebController(ctx, self.history_reads, self.promote)
        self.list_state = AuthorizedSessionList(ctx, self.list_work_slice_ms)
        await self.commands.initialize()
        ctx.fiber.assert_active()
        await self.list_state.initialize()
        ctx.fiber.assert_active()
        ctx.plugin(SessionFileReferences)
        ctx.plugin(CurrentSessionMediaReferences)
        ctx.plugin(AuthorizedSessionSkillCatalog)
        ctx.plugin(ArchivedSessionGate)
        ctx.on('session/created', lambda session: ctx.emit('api-session/added', self.list_state.summaryFor(session)))
        ctx.on('session/disposed', lambda session: ctx.emit('api-session/removed', session.id))
        def availability(payload):
            agent = payload['agent']
            if ctx.get('sessions').get(agent.id) is agent.session:
                ctx.emit('api-session/added', self.list_state.summaryFor(agent.session))
        ctx.on('agent/created', availability)
        ctx.on('agent/disposed', availability)
        ctx.on('agent/status', lambda payload: ctx.emit('api-session/status', payload['agent'].id, payload['status']=='running'))
        ctx.on('agent/error', lambda payload: ctx.emit('api-session/error', payload['agent'].id, error_chain(payload['error'])))
        ctx.on('session/event', self.event)

    def event(self, session, event):
        if event['type'] == 'user/message' and event['data']['source']['kind'] == 'user':
            self.ctx.emit('api-session/activity', session.id, event['time'])

    async def verifyDesktopPath(self, path, signal):
        if not path:
            raise RemoteError('gateway/bad-request', 'A non-empty file path is required', {})
        signal.throwIfAborted()
        host_path = os.path.abspath(path)
        fs = self.ctx.get('fs')
        mapped = fs.processPathFromHostPath(host_path)
        if mapped is None or fs.processPath(await fs.resolve(mapped, dict(signal=signal))) != host_path:
            raise RemoteError('gateway/bad-request', 'Path has no verified Host path', {})
        signal.throwIfAborted()
        return host_path

    @Remote
    async def openWorkspacePath(self, request, signal):
        try:
            path = await self.verifyDesktopPath(request['path'], signal)
            if request.get('action') == 'reveal':
                await self.reveal_path(path, signal)
            elif 'application' in request:
                await self.open_file_application(path, request['application'], signal)
            else:
                await self.open_path(path, signal)
            return dict(opened=True)
        except Exception as error:
            if signal.aborted:
                raise RemoteError('gateway/cancelled', 'path open was aborted', {}) from None
            if isinstance(error, RemoteError):
                raise
            raise RemoteError('gateway/internal', 'path open failed', {}, cause=error) from None

    @Remote
    async def workspacePathApplications(self, request, signal):
        if not self.can_open():
            return []
        try:
            path = await self.verifyDesktopPath(request['path'], signal)
            return await self.file_applications(path, signal)
        except Exception as error:
            if signal.aborted:
                raise RemoteError('gateway/cancelled', 'application query was aborted', {}) from None
            if isinstance(error, RemoteError):
                raise
            raise RemoteError('gateway/internal', 'file application query failed', {}, cause=error) from None

    @Remote
    async def prompt(self, request, signal):
        signal.throwIfAborted()
        if request['content'] and not has_prompt_content(request['content']):
            raise RemoteError('gateway/bad-request', 'prompt content must include non-whitespace text or an attachment', {})
        zone = canonical_client_time_zone(request['clientTimeZone']) if 'clientTimeZone' in request else None
        if 'clientTimeZone' in request and zone is None:
            raise RemoteError('session/invalid-time-zone', 'clientTimeZone must be UTC or a valid IANA Area/Location name', dict(value=request['clientTimeZone']))
        source = dict(kind='user' if request['content'] else 'retry', rpcId=request['requestId'])
        if zone is not None:
            source['clientTimeZone'] = zone
        principal = principal_of(getattr(self.ctx, 'invocation', None))
        if principal is not UNDEFINED:
            source['principal'] = principal
        return await self.commands.prompt(request, source)

    def allows_session(self, identity):
        return self.ctx.get('remoteAccess').allows(dict(kind='session', id=identity))

    @Remote
    async def events(self, request, signal):
        return await self.history_reads.events(request, signal)

    @Remote
    async def page(self, request, signal):
        return await self.history_reads.events(request, signal)

    @Remote
    async def projections(self, request, signal):
        return await self.history_reads.projections(request, signal)

    @Remote(dict(mode='stream'))
    def observeEvent(self, request, signal):
        return self.history_reads.observeEvent(request, signal)

    @Remote(dict(mode='stream'))
    def observeProjections(self, request, signal):
        return self.history_reads.observeProjections(request, signal)

    @Remote(dict(mode='stream'))
    def follow(self, request, signal):
        return self.web_controller.follow(request, signal)

    @Remote
    async def state(self, request, signal):
        return await self.state_controller.state(request, signal)

    @Remote(dict(mode='stream'))
    def observeState(self, request, signal):
        return self.state_controller.observeState(request, signal)

    @Remote
    async def wait(self, request, signal):
        return await self.state_controller.wait(request, signal)

    @Remote
    async def list(self, _request, signal):
        items = await self.list_state.list(signal)
        return dict(items=[item for item in items if self.allows_session(item['sessionId'])])

    @Remote
    async def search(self, request, signal):
        result = await self.list_state.search(request['query'], signal)
        return dict(result, items=[item for item in result['items'] if self.allows_session(item['sessionId'])])

    @Remote(dict(mode='stream'))
    async def control(self, signal):
        source = self.control_state.control(signal)
        try:
            async for frame in source:
                if frame['type'] == 'baseline':
                    projections = {identity:value for identity,value in frame['value']['projections'].items() if self.allows_session(identity)}
                    yield dict(type='baseline', value=dict(frame['value'], projections=projections))
                elif frame['type'] == 'projection':
                    if self.allows_session(frame['sessionId']):
                        yield frame
                else:
                    raise ValueError('unhandled Session control frame: ' + str(frame['type']))
        finally:
            await source.aclose()
