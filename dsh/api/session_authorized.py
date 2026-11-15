"""Resource-filtered Session Remote reads and v4 projection control frames."""
from dsh.api.session_current import CurrentSessionController
from dsh.api.session_control_current import CurrentSessionControl
from dsh.typert.remote import Remote


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

    def allows_session(self, identity):
        return self.ctx.get('remoteAccess').allows(dict(kind='session', id=identity))

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
