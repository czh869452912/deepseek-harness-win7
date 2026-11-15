"""Resource-filtered Session Remote reads and v4 projection control frames."""
from dsh.api.session_current import CurrentSessionController
from dsh.api.session_control_current import CurrentSessionControl
from dsh.typert.remote import Remote, RemoteError
from dsh.typert.principal import principal_of
from dsh.core.session.json import UNDEFINED
from dsh.api.session_commands_authorized import AuthorizedSessionCommands
from dsh.api.session_commands_current import has_prompt_content
from dsh.util_time import canonical_client_time_zone
from dsh.api.session_agents_authorized import AuthorizedSessionAgents
from dsh.api.session_history_authorized import SessionHistoryReads


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
    inject = ['agentDefaultModel', 'agents', 'attachments', 'fileUploads', 'fs', 'llm', 'remoteAccess',
              'sessions', 'sessionProjections', 'sessionQuery', 'typert', 'typertGateway', 'workspaceRegistry']
    control_class = ProjectionSessionControl
    commands_class = AuthorizedSessionCommands
    agents_class = AuthorizedSessionAgents
    model_projection = staticmethod(lambda ctx: None)

    async def init(self):
        self.history_reads = SessionHistoryReads(self.ctx)
        await self.commands.initialize()

    def event(self, session, event):
        if event['type'] == 'user/message' and event['data']['source']['kind'] == 'user':
            self.ctx.emit('api-session/activity', session.id, event['time'])

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
