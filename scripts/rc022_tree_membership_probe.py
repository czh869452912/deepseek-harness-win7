"""Pair runtime ownership, names and durable creation ancestry without activating ancestors."""
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


class Agent:
    def __init__(self, identity, origin=None, own=False):
        self.id = identity
        self.session = SimpleNamespace(header=dict(id=identity,**(dict(origin=origin) if origin else {})),
                                       isOwnSeq=lambda seq: own)


async def observe():
    from dsh.subagent.tree import SubagentTree
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    rows = []
    for action in ('root','ordinary-fork','own-descriptor','origin','resident','creator-gone','stale-caller',
                   'stale-root','stale-activation','external','named','unnamed','unnamed-parent','tree-closing',
                   'child-closing','manager-closing','name-lead','name-known','name-id','name-missing-path'):
        root, parent, child = Agent('root'),Agent('parent','subagent',True),Agent('child','subagent',True)
        ordinary = Agent('ordinary',own=False)
        live = {agent.id:agent for agent in (root,parent,child,ordinary)}
        identity = lambda session: None if session is root.session else dict(seq=1)
        async def query(identity, options):
            entries = [dict(id='child',mode='continuable',name='worker',label='Task',createdAt=1)] if identity=='root' else []
            return SimpleNamespace(projections=dict(values=dict(subagentCatalog=entries)),dispose=lambda:None)
        services = dict(agents=SimpleNamespace(get=live.get),sessionQuery=SimpleNamespace(observeSession=query))
        tree = SubagentTree(SimpleNamespace(get=services.get),SimpleNamespace(identityOf=identity,catalogOf=lambda session:[]))
        parent_activation = SimpleNamespace(kind='local',handle=SimpleNamespace(agent=parent),root=root,ancestors=['root'],path='worker',closing=None)
        activation = SimpleNamespace(kind='local',handle=SimpleNamespace(agent=child),root=root,ancestors=['root','parent'],path='worker/nested',closing=None)
        tree.resident.update(parent=parent_activation,child=activation)
        caller = child
        if action=='root': caller=root
        elif action=='ordinary-fork': caller=ordinary
        elif action=='own-descriptor': caller=Agent('own',own=True);live[caller.id]=caller
        elif action=='origin': caller=Agent('origin','subagent');live[caller.id]=caller
        elif action=='creator-gone': live.pop('parent');tree.resident.pop('parent')
        elif action=='stale-caller': live['child']=Agent('child')
        elif action=='stale-root': live['root']=Agent('root')
        elif action=='stale-activation': activation.handle.agent=Agent('child')
        elif action=='external': activation.kind='external'
        elif action=='unnamed': activation.path=UNDEFINED
        elif action=='unnamed-parent': activation.path=UNDEFINED;tree.resident.pop('parent')
        elif action=='tree-closing': tree.closing_roots.add(root)
        elif action=='child-closing': activation.closing=object()
        elif action=='manager-closing': tree.draining=True
        row = dict(kind='live',action=action)
        try:
            if action.startswith('name-'):
                name={'name-lead':'lead','name-known':'worker','name-id':'historical-id','name-missing-path':'worker/missing'}[action]
                row['value']=await tree.resolve_name(caller,name)
            else:
                row.update(root=tree.root_of(caller).id,names=tree.names_of(caller),
                           ancestors=tree.ancestry_for_child(caller)['ancestors'])
                tree.assert_admitting(caller)
        except Exception as error: row['error']=dict(code=getattr(error,'code',None),message=str(error))
        rows.append(row)
    for action in ('normal','implicit-root','unnamed','missing-edge','cycle','inherited-identity',
                   'no-identity','no-parent','foreign-root','root-cold','delegated-root','unavailable','abort','missing-query'):
        root=Agent('root');live={'root':root};trace=[];controller=AbortController()
        def node(identity,parent=None,name=None):
            return SimpleNamespace(header=dict(id=identity,**(dict(parentSession=parent) if parent else {})),
                projections=dict(values=dict(subagent=None if parent is None else dict(seq=2),subagentCatalog=[])),
                inheritedEventCount=0)
        nodes=dict(root=node('root'),parent=node('parent','root'),child=node('child','parent'))
        nodes['root'].projections['values']['subagentCatalog']=[dict(id='parent',name='worker')]
        nodes['parent'].projections['values']['subagentCatalog']=[dict(id='child',name='nested')]
        explicit=root
        if action=='implicit-root': explicit=None
        elif action=='unnamed': nodes['root'].projections['values']['subagentCatalog'][0].pop('name')
        elif action=='missing-edge': nodes['parent'].projections['values']['subagentCatalog']=[]
        elif action=='cycle': nodes['parent'].header['parentSession']='child'
        elif action=='inherited-identity': nodes['child'].inheritedEventCount=3
        elif action=='no-identity': nodes['child'].projections['values']['subagent']=None
        elif action=='no-parent': nodes['child'].header.pop('parentSession')
        elif action=='foreign-root': explicit=Agent('other')
        elif action=='root-cold': explicit=None;live.clear()
        elif action=='delegated-root': explicit=None;nodes['root'].header['origin']='subagent'
        elif action=='abort': controller.abort()
        async def query(identity,options):
            trace.append('read:'+identity)
            if action=='unavailable': raise RuntimeError('storage')
            source=nodes[identity]
            return SimpleNamespace(**source.__dict__,dispose=lambda:trace.append('dispose:'+identity))
        services=dict(agents=SimpleNamespace(get=live.get),sessionQuery=SimpleNamespace(observeSession=query))
        if action=='missing-query': services.pop('sessionQuery')
        tree=SubagentTree(SimpleNamespace(get=services.get),SimpleNamespace(identityOf=lambda session:None))
        row=dict(kind='ancestry',action=action)
        try:
            value=await tree.resolve_creation_ancestry(nodes['child'],controller.signal,explicit)
            row['value']=dict(root=value['root'].id,ancestors=value['ancestors'],path=None if value['path'] is UNDEFINED else value['path'])
        except Exception as error:
            row['error']=dict(code=getattr(error,'code',None),message='aborted' if controller.signal.aborted else str(error))
        row['trace']=trace;rows.append(row)
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_tree_membership.mts','Exact live runtime ownership and creation ancestry, ordinary fork exclusion, member names, selective path resolution, closing admission, scoped cold parent reads and cancellation.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/tree.py',ROOT/'dsh/subagent/list_children.py'])
