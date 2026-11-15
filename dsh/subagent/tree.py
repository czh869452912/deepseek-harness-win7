"""Tree membership from exact live ownership and verified durable creation edges."""
import json

from dsh.core.abort import NEVER_ABORTED
from dsh.core.session.json import UNDEFINED
from dsh.subagent.catalog import catalog_names
from dsh.subagent.errors import SubagentError
from dsh.subagent.list_children import resolve_agent_path
from dsh.subagent.names import (ROOT_AGENT_NAME, SiblingNameReservations, agent_address,
                                join_agent_path, parent_agent_path)


def activation_agent(activation):
    return activation.handle.agent if activation.kind == 'local' else None


class SubagentTree:
    """Membership part of the manager; the same residency map owns execution."""

    def __init__(self, ctx, host):
        self.ctx, self.host = ctx, host
        self.resident = {}
        self.names = SiblingNameReservations()
        self.closing_roots = set()
        self.draining = False

    def root_of(self, caller):
        agents = self.ctx.get('agents')
        if agents.get(caller.id) is not caller:
            raise SubagentError('subagent tree access requires the exact live caller', 'UNAUTHORIZED')
        identity = self.host.identityOf(caller.session)
        delegated = (caller.session.header.get('origin') == 'subagent'
                     or identity is not None and caller.session.isOwnSeq(identity['seq']))
        activation = self.resident.get(caller.id)
        if (activation is not None and activation_agent(activation) is caller
                and agents.get(activation.root.id) is activation.root):
            return activation.root
        if delegated or activation is not None:
            raise SubagentError('agent has no active runtime owner', 'UNAUTHORIZED')
        return caller

    def ancestry_for_child(self, creator):
        root = self.root_of(creator)
        activation = self.resident.get(creator.id)
        return dict(root=root, ancestors=list(activation.ancestors if activation is not None else [])+[creator.id])

    def reserve_name(self, parent, requested=UNDEFINED):
        return self.names.reserve(parent, catalog_names(self.host.catalogOf(parent.session)), requested)

    def path_of(self, member, root):
        if member is root:
            return ''
        activation = self.resident.get(member.id)
        return activation.path if activation is not None else UNDEFINED

    def names_of(self, agent):
        root = self.root_of(agent)
        if root is agent:
            return dict(self=ROOT_AGENT_NAME)
        activation = self.resident[agent.id]
        parent_id = activation.ancestors[-1]
        if activation.path is UNDEFINED:
            parent = self.resident.get(parent_id)
            parent_path = '' if parent_id == root.id else parent.path if parent is not None else UNDEFINED
        else:
            parent_path = parent_agent_path(activation.path)
        return dict(self=agent_address(activation.path,agent.id), parent=agent_address(parent_path,parent_id))

    async def resolve_name(self, caller, name, signal=NEVER_ABORTED):
        root = self.root_of(caller)
        if name == ROOT_AGENT_NAME:
            return root.id
        resolved = await resolve_agent_path(self.ctx,root.id,name,signal)
        if resolved is not UNDEFINED:
            return resolved
        if '/' in name:
            raise SubagentError('agent name %s was not found in this subagent tree; use list_agents to see the names'
                                % json.dumps(name,ensure_ascii=False), 'AGENT_NAME_NOT_FOUND')
        return name

    def require_session_query(self):
        query = self.ctx.get('sessionQuery')
        if query is None:
            raise SubagentError('continuable subagents require session query (load @deepseek-ai/dsh-session-query)',
                                'CONTINUATION_UNAVAILABLE')
        return query

    async def observe_continuation(self, child_id, signal):
        query = self.require_session_query()
        try:
            return await query.observeSession(child_id,dict(signal=signal))
        except Exception as cause:
            signal.throwIfAborted()
            error = SubagentError('subagent "%s" is unavailable' % child_id,'NOT_RESUMABLE')
            error.cause = cause
            raise error

    async def resolve_creation_ancestry(self, source, signal, root=None):
        ancestors, names, seen = [], [], {source.header['id']}
        header, projections, cut = source.header, source.projections, source.inheritedEventCount
        def path_from_root():
            path = ''
            for name in names:
                path = join_agent_path(path,name)
            return path
        while True:
            signal.throwIfAborted()
            parent_id = header.get('parentSession')
            identity = projections.get('values',{}).get('subagent') if projections is not None else None
            if parent_id is None or identity is None or identity['seq'] < cut:
                break
            if parent_id in seen:
                raise SubagentError('cyclic subagent creation ancestry','UNAUTHORIZED')
            seen.add(parent_id)
            parent = await self.observe_continuation(parent_id,signal)
            try:
                entries = parent.projections.get('values',{}).get('subagentCatalog',[]) if parent.projections is not None else []
                entry = next((entry for entry in entries if entry['id'] == header['id']),None)
                if entry is None:
                    raise SubagentError('subagent is absent from its creator catalog','UNAUTHORIZED')
                ancestors.insert(0,parent_id)
                names.insert(0,entry.get('name',UNDEFINED))
                if root is not None and parent_id == root.id:
                    return dict(root=root,ancestors=ancestors,path=path_from_root())
                header, projections, cut = parent.header, parent.projections, parent.inheritedEventCount
            finally:
                parent.dispose()
        if root is None and ancestors and header.get('origin') != 'subagent':
            owner = self.ctx.get('agents').get(header['id'])
            if owner is None or self.root_of(owner) is not owner:
                raise SubagentError('subagent tree root is not live','CONTINUATION_UNAVAILABLE')
            return dict(root=owner,ancestors=ancestors,path=path_from_root())
        raise SubagentError('agent "%s" is not a member of this subagent tree' % source.header['id'],'UNAUTHORIZED')

    def closing_teardown_for(self, agent):
        if self.draining:
            return 'manager'
        root = self.root_of(agent)
        return root if root in self.closing_roots else None

    def assert_admitting(self, agent):
        closing = self.closing_teardown_for(agent)
        if closing is None:
            activation = self.resident.get(agent.id)
            if activation is not None and activation.closing is not None:
                raise SubagentError('subagent "%s" is closing' % agent.id,'ACTIVATION_CLOSING')
            return
        message = ('subagents are draining; the operation was not admitted' if closing == 'manager' else
                   'subagent tree "%s" is draining; the operation was not admitted' % closing.id)
        raise SubagentError(message,'DRAINING')

    rootOf = root_of
    namesOf = names_of
    resolveName = resolve_name
