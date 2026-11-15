"""Pair resource-aware Remote declaration snapshots and option validation."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.typert.remote import Remote, RemoteScope, remote_methods
    from dsh.typert.access import call_resources
    from dsh.typert.principal import principal_of
    from dsh.core.session.json import UNDEFINED
    rows=[];readers=dict(session=lambda request:request['sessions'])
    class Marked:
        @Remote
        def plain(self, request):pass
        @Remote(dict(name='watch',mode='stream',resources=readers))
        def observe(self, request):pass
        @RemoteScope('agent',dict(name='write',resources=dict(session=lambda identity:identity)))
        def scoped(self, identity):pass
    # Reader table is copied when the declaration is made.
    readers['session']=lambda _: 'mutated'
    service=Marked()
    for marker in remote_methods(service):
        values=dict(marker);resources=values.pop('resources',None)
        if resources is not None:
            values['read']=resources['session'](dict(sessions=['a','b']) if marker['method']=='observe' else 'scope')
            try:resources['session']=lambda _: 'mutated';values['frozen']=False
            except TypeError:values['frozen']=True
        rows.append(values)
    snapshot=remote_methods(service);snapshot[0]['method']='changed'
    rows.append(dict(snapshotSafe=remote_methods(service)[0]['method']=='plain'))
    for scoped in [False,True]:
        for option in [{},dict(unknown=True),dict(mode='unary'),dict(resources={}),dict(resources=dict(session=7))]:
            try:(RemoteScope('agent',option) if scoped else Remote(option))
            except Exception as error:rows.append(dict(scoped=scoped,error=str(error)))
    class Base:
        @Remote(dict(resources=dict(session=lambda value:value)))
        def inherited(self, value):pass
    class Child(Base):
        @Remote('another')
        def child(self, value):pass
    rows.append(dict(inherited=[marker['method'] for marker in remote_methods(Child())]))
    for value in [None,dict(peer=dict(principal=dict(kind='owner'))),dict(peer=dict(principal=dict(kind='guest',id='g'))),dict(peer=dict(principal=dict(kind='Owner')))]:
        principal=principal_of(value);rows.append(dict(principal=None if principal is UNDEFINED else principal))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_remote_markers.mts','Remote/RemoteScope resource reader declarations, frozen copied reader tables, safe snapshots, option refusal, inheritance and principal extraction.',
        [Path(__file__).resolve(),ROOT/'dsh/typert/remote.py',ROOT/'dsh/typert/principal.py'])
