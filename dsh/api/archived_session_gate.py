"""Controller admission for archived ordinary Sessions and child lineages."""
from dsh.cordis.plugin import Plugin


def under_archived_session(ctx, agent):
    archived = ctx.get('workspaceRegistry').archivedSessionIds
    header, visited = agent.session.header, set()
    while header.id not in visited:
        if header.id in archived:
            return True
        visited.add(header.id)
        if header.origin != 'subagent' or header.parentSession is None:
            return False
        parent = ctx.get('sessions').get(header.parentSession)
        if parent is None:
            return header.parentSession in archived
        header = parent.header
    return False


class ArchivedSessionGate(Plugin):
    name = 'archived-session-gate'
    inject = ['agents', 'sessions', 'workspaceRegistry']

    def apply(self, ctx):
        async def admit(payload, next_fn):
            if under_archived_session(ctx, payload['agent']):
                return dict(kind='reject')
            return await next_fn()
        ctx.on('agent/pre-step', admit)
