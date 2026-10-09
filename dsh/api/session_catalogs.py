"""Agent-scoped file references and cold-readable skill metadata."""
from dsh.api.settings import failure, settled
from dsh.core.scope import scope_of
from dsh.session.session_query import SessionQueryError
from dsh.typert.remote import Remote, TypertRemoteService


class SessionFileReferences(TypertRemoteService):
    inject = ['fileReferences', 'typert']

    def __init__(self, ctx):
        super().__init__(ctx, 'sessionFileReferences', {'namespace': 'fileReferences'})

    @Remote
    async def list(self, agent, query, signal):
        return await self.ctx.get('fileReferences').list(agent, query, signal)


class SessionSkillCatalog(TypertRemoteService):
    inject = ['agents', 'sessionQuery', 'typert']

    def __init__(self, ctx):
        super().__init__(ctx, 'sessionSkillCatalog', {'namespace': 'skills'})

    @Remote
    async def list(self, request, signal):
        sid = request['sessionId']
        try:
            source = await self.ctx.get('sessionQuery').observeSession(sid)
            try:
                cwd, preset = source.header.cwd, source.projections['values'].get('agentPreset')
            finally:
                source.dispose()
        except SessionQueryError as error:
            if error.code == 'SESSION_QUERY_SESSION_NOT_FOUND':
                raise failure('session-not-found', 'session "%s" not found' % sid, {'sessionId': sid}) from error
            raise failure('internal', 'session "%s" could not be inspected: %s' % (sid, error)) from error
        if cwd is None:
            raise failure('internal', 'session "%s" has no project cwd' % sid)
        live, presets = self.ctx.get('agents').get(sid), self.ctx.get('agentPresets')
        registry = presets.serviceFor(live, 'skills') if live is not None and presets is not None else None
        registry = registry if registry is not None else self.ctx.get('skills')
        if registry is None:
            raise failure('internal', "skill registry is absent: neither this session's agent preset nor the host composition mounts @deepseek-ai/dsh-skill")
        scope = scope_of(live.ctx) if live is not None else None
        if scope is None and presets is not None:
            try:
                scope = await presets.standingKeyFor(preset)
            except Exception:
                pass
        try:
            rows = await settled(registry.list(dict(cwd=cwd, scope=scope)))
            return dict(skills=[dict({key: row[key] for key in ('name', 'description', 'whenToUse') if key in row},
                                    modelInvocable=row['invocation']['modelInvocable'])
                               for row in rows if row['invocation']['userInvocable']])
        except Exception as error:
            raise failure('internal', 'skill listing failed: ' + str(error)) from error
