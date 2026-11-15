"""Workspace archive admission for verified and unpublished subagent descendants."""
from dsh.cordis.awaiting import await_callback_result


def header_ancestors(ctx, agent):
    ancestors,visited = [],{agent.id}
    header = agent.session.header
    while (header.get('origin') == 'subagent' and header.get('parentSession') is not None
           and header['parentSession'] not in visited):
        parent_id = header['parentSession']
        ancestors.append(parent_id)
        visited.add(parent_id)
        parent = ctx.get('agents').get(parent_id)
        if parent is None:
            break
        header = parent.session.header
    return ancestors


def install_subagent_archive_admission(ctx, resident_ancestors, identity_of):
    def ancestors_of(agent):
        resident = resident_ancestors(agent)
        return header_ancestors(ctx,agent) if resident is None else resident
    def running_descendants(session_id):
        return [agent for agent in ctx.get('agents').list() if agent.status == 'running' and session_id in ancestors_of(agent)]
    async def activity(request, next_fn):
        running = running_descendants(request['sessionId'])
        rest = await await_callback_result(next_fn())
        if not running:
            return rest
        items = []
        for child in running:
            identity = identity_of(child.session)
            label = identity.get('label') if identity is not None and child.session.isOwnSeq(identity['seq']) else None
            items.append(dict(id=child.id,**(dict(label=label) if label is not None else {})))
        return [dict(kind='subagent',items=items)]+rest
    def stop(request):
        for child in running_descendants(request['sessionId']):
            try:
                child.cancel(dict(kind='parent'))
            except Exception as error:
                ctx.logger.warn('subagent: cancelling "%s" for an archived Session failed: %s' % (child.id,error))
    def pre_step(payload, next_fn):
        registry = ctx.get('workspaceRegistry')
        archived = getattr(registry,'archivedSessionIds',None) if registry is not None else None
        if archived is not None and any(identity in archived for identity in ancestors_of(payload['agent'])):
            return dict(kind='reject')
        return next_fn()
    ctx.on('workspace/session-activity',activity)
    ctx.on('workspace/session-stop',stop)
    ctx.on('agent/pre-step',pre_step)


installSubagentArchiveAdmission = install_subagent_archive_admission
