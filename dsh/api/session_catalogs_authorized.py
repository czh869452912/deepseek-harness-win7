"""Passive Session skill reads with directory and preset lease ownership."""
from dsh.api.session_commands_current import error_text
from dsh.api.settings import settled
from dsh.session.session_query import SessionQueryError
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService


class AuthorizedSessionSkillCatalog(TypertRemoteService):
    inject = ['agents', 'sessionQuery', 'typert', 'workingDirectory']

    def __init__(self, ctx):
        super().__init__(ctx, 'sessionSkillCatalog', dict(namespace='skills'))

    async def scope_for(self, preset):
        presets = self.ctx.get('agentPresets')
        if presets is not None:
            try:
                return await presets.acquireScope(preset)
            except Exception:
                # Unknown or unusable recorded compositions use the global view.
                pass

    @Remote
    async def list(self, request, signal):
        sid = request['sessionId']
        try:
            observation = await self.ctx.get('sessionQuery').observeSession(sid)
            try:
                if observation.projections is None:
                    raise RuntimeError('skill catalog requires a projected Session observation')
                values = observation.projections['values']
                cwd = values.get('workingDirectory')
                if cwd is None:
                    cwd = observation.header.cwd
                if cwd is None:
                    cwd = self.ctx.get('workingDirectory').defaultDirectory
                preset = values.get('agentPreset')
                live = self.ctx.get('agents').get(sid)
                if live is not None:
                    cwd = await self.ctx.get('workingDirectory').ensure(live, signal)
            finally:
                observation.dispose()
        except Exception as error:
            if isinstance(error, SessionQueryError) and error.code == 'SESSION_QUERY_SESSION_NOT_FOUND':
                raise RemoteError('session/not-found', 'session "{}" not found'.format(sid), dict(sessionId=sid)) from None
            raise RemoteError('gateway/internal', 'session "{}" could not be inspected: {}'.format(sid, error_text(error)), {}) from None

        live, presets = self.ctx.get('agents').get(sid), self.ctx.get('agentPresets')
        scoped = presets.serviceFor(live, 'skills') if live is not None and presets is not None else None
        registry = scoped if scoped is not None else self.ctx.get('skills')
        if registry is None:
            raise RemoteError('gateway/internal', "skill registry is absent: neither this session's agent preset nor the host composition mounts @deepseek-ai/dsh-skill", {})
        lease = await self.scope_for(preset) if live is None else None
        scope = live if live is not None else lease.key if lease is not None else None
        try:
            try:
                skills = await settled(registry.list(dict(cwd=cwd, scope=scope)))
                return dict(skills=[dict({key: row[key] for key in ('name', 'path', 'description', 'whenToUse') if key in row},
                    modelInvocable=row['invocation']['modelInvocable']) for row in skills if row['invocation']['userInvocable']])
            except Exception as error:
                raise RemoteError('gateway/internal', 'skill listing failed: ' + error_text(error), {}) from None
        finally:
            if lease is not None:
                await lease.dispose()
