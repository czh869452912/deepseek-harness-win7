"""Current handle observations: cold ownership, revision cuts and cancellation."""
import copy
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.core.session.current_session import CurrentSessionStore, CurrentSessionPlugin
from dsh.cordis.context import Context
from dsh.cordis.errors import ThrownValueError
from dsh.session.cold_read import readColdSessionLog
from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistence
from dsh.session.observation_current import CurrentSessionObservationReader
from dsh.session.persistence import SessionPersistenceCorruptionError, SessionPersistenceNotFoundError
from dsh.session.session_query import SessionQueryError


def header(sid='cold'):
    return dict(version=3,id=sid,createdAt=1,isSeeded=False,cwd='/workspace')


def events():
    return [dict(type='turn/start',seq=0,time=1,data=dict(turn=1))]


class Persistence:
    def __init__(self):
        self.entries={sid:dict(header=header(sid),events=events(),revision='r1') for sid in ('cold','b','c','d')}
        self.calls=[]
        self.hooks={}

    async def stat(self,sid,options=None):
        self.calls.append(('stat',sid))
        entry=self.entries.get(sid)
        self.hooks.get('stat',lambda:None)()
        return None if entry is None else dict(header=copy.deepcopy(entry['header']),revision=entry['revision'])

    async def open(self,sid,access,options=None):
        self.calls.append(('open',sid,access))
        if sid not in self.entries:
            raise SessionPersistenceNotFoundError(sid)
        entry=self.entries[sid]
        async def read(offset=0,length=None,options=None):
            self.calls.append(('read',sid))
            self.hooks.get('read',lambda:None)()
            return dict(eventState='detached',events=copy.deepcopy(entry['events']))
        async def close():
            self.calls.append(('close',sid))
            self.hooks.get('close',lambda:None)()
        return SimpleNamespace(header=copy.deepcopy(entry['header']),inheritedEventCount=0,read=read,close=close)


@pytest.fixture
def setup():
    ctx=SimpleNamespace(services={})
    ctx.get=lambda key:ctx.services.get(key)
    ctx.services['sessions']=CurrentSessionStore(None)
    p=Persistence();ctx.services['sessionPersistence']=p
    return ctx,p,CurrentSessionObservationReader(ctx,1)


@pytest.mark.asyncio
async def test_cold_balance_never_attaches_or_writes_and_cache_is_pinned(setup):
    ctx,p,reader=setup
    first=await reader.read('cold');retained=first.retain()
    assert first.source=='prepared' and first.cursor==1 and first.revision=='r1'
    assert [e['type'] for e in first.events]==['turn/start','turn/end']
    assert len(p.entries['cold']['events'])==1 and not ctx.get('sessions').list()
    cached=await reader.read('cold');assert cached.events is first.events
    assert len([c for c in p.calls if c[0]=='read'])==1
    second=await reader.read('b');assert len(reader.cache)==2
    first.dispose();first.dispose();cached.dispose()
    assert 'cold' in reader.cache
    retained.dispose();assert list(reader.cache)==['b']
    with pytest.raises(ValueError,match='is disposed'):first.retain()
    second.dispose()


@pytest.mark.asyncio
async def test_revision_replacement_and_provider_identity_preserve_old_lease(setup):
    ctx,p,reader=setup
    first=await reader.read('cold')
    p.entries['cold'].update(events=[],revision='r2')
    second=await reader.read('cold')
    assert second.cursor==-1 and first.cursor==1 and len(first.events)==2
    ctx.services['sessionPersistence']=Persistence()
    third=await reader.read('cold')
    assert third.revision=='r1' and third.events is not first.events
    for lease in (first,second,third):lease.dispose()


@pytest.mark.asyncio
async def test_lru_eviction_continues_past_pins_and_release_reduces_bound(setup):
    ctx,p,reader=setup
    reader.cacheCapacity=2
    a=await reader.read('cold');b=await reader.read('b');c=await reader.read('c')
    assert len(reader.cache)==3
    b.dispose();assert list(reader.cache)==['cold','c']
    d=await reader.read('d');assert len(reader.cache)==3
    c.dispose();assert list(reader.cache)==['cold','d']
    a.dispose();d.dispose()


@pytest.mark.asyncio
async def test_live_cut_is_lazy_shared_and_stable(setup,monkeypatch):
    ctx,p,reader=setup
    store=ctx.get('sessions');session=store.create('cold')
    session.append('turn/start',dict(turn=1))
    calls=[];original=session.snapshotEvents
    def snapshot(*args):calls.append(args);return original(*args)
    monkeypatch.setattr(session,'snapshotEvents',snapshot)
    first=await reader.read('cold',dict(projectionMode='none'));retained=first.retain()
    assert first.projections is None and retained.projections is None
    session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
    assert not calls and not p.calls and first.cursor==0
    assert len(first.events)==1 and first.events is retained.events and len(calls)==1
    first.dispose();assert len(retained.events)==1
    with pytest.raises(ValueError):first.retain()
    retained.dispose()


@pytest.mark.parametrize('point',['stat','read','prepare'])
@pytest.mark.asyncio
async def test_attach_races_prefer_live_owner(setup,point,monkeypatch):
    ctx,p,reader=setup
    store=ctx.get('sessions')
    def attach():store.create('cold')
    if point=='prepare':
        original=store.prepare
        def prepare(*args,**kwargs):
            monkeypatch.setattr(store,'prepare',original);attach();raise ValueError('live owner')
        monkeypatch.setattr(store,'prepare',prepare)
    else:p.hooks[point]=attach
    observation=await reader.read('cold')
    assert observation.source=='live' and observation.cursor==-1
    observation.dispose()


@pytest.mark.parametrize('point',['before','stat','read','close'])
@pytest.mark.asyncio
async def test_abort_at_each_boundary(setup,point):
    ctx,p,reader=setup;controller=AbortController();reason=RuntimeError('cancel')
    abort=lambda:controller.abort(reason)
    if point=='before':abort()
    else:p.hooks[point]=abort
    with pytest.raises(SessionQueryError) as caught:
        await reader.read('cold',dict(signal=controller.signal))
    assert caught.value.code=='SESSION_QUERY_ABORTED' and caught.value.cause is reason
    if point in ('read','close'):assert ('close','cold') in p.calls


@pytest.mark.parametrize('point',['stat','read','close'])
@pytest.mark.parametrize('kind',['missing','corrupt','ordinary','non-error'])
@pytest.mark.asyncio
async def test_persistence_error_taxonomy_and_handle_cleanup(setup,point,kind):
    ctx,p,reader=setup
    failure={'missing':SessionPersistenceNotFoundError('cold'),
             'corrupt':SessionPersistenceCorruptionError('bad bytes'),
             'ordinary':RuntimeError('io failure'),'non-error':ThrownValueError('rejected')}[kind]
    def fail():raise failure
    p.hooks[point]=fail
    with pytest.raises(SessionQueryError) as caught:await reader.read('cold')
    code={'missing':'SESSION_QUERY_SESSION_NOT_FOUND','corrupt':'SESSION_QUERY_CORRUPT_SESSION'}.get(kind,'SESSION_QUERY_PERSISTENCE_FAILED')
    assert caught.value.code==code
    assert caught.value.cause is (failure.value if kind=='non-error' else failure)
    if point in ('read','close'):assert ('close','cold') in p.calls


@pytest.mark.asyncio
async def test_read_primary_failure_survives_secondary_close_failure(setup):
    ctx,p,reader=setup;primary=RuntimeError('read failed')
    def fail():raise primary
    def close_fail():raise RuntimeError('close failed')
    p.hooks.update(read=fail,close=close_fail)
    with pytest.raises(RuntimeError) as caught:await readColdSessionLog(p,'cold')
    assert caught.value is primary


@pytest.mark.asyncio
async def test_missing_mismatched_and_invalid_stored_header(setup):
    ctx,p,reader=setup
    with pytest.raises(SessionQueryError) as caught:await reader.read('absent')
    assert caught.value.code=='SESSION_QUERY_SESSION_NOT_FOUND'
    p.entries['cold']['header']['id']='other'
    with pytest.raises(SessionQueryError) as caught:await reader.read('cold')
    assert caught.value.code=='SESSION_QUERY_SOURCE_CONFLICT'
    p.entries['cold']['header']=header();p.entries['cold']['events'][0]['seq']=7
    with pytest.raises(SessionQueryError) as caught:await reader.read('cold')
    assert caught.value.code=='SESSION_QUERY_CORRUPT_SESSION'


@pytest.mark.parametrize('cached',[False,True])
@pytest.mark.asyncio
async def test_projection_hydration_failure_and_opt_out(setup,cached):
    ctx,p,reader=setup;calls=[]
    def hydrate(*args):calls.append(args);return dict(result='ok')
    registry=SimpleNamespace(hydrate=hydrate,snapshot=hydrate)
    ctx.services['sessionProjections']=registry
    if cached:ctx.services['sessionProjectionCache']=SimpleNamespace(hydratePrepared=hydrate)
    lease=await reader.read('cold');assert lease.projections==dict(result='ok') and len(calls)==1
    lease.dispose()
    def fail(*args):raise RuntimeError('projection')
    if cached:ctx.get('sessionProjectionCache').hydratePrepared=fail
    else:registry.hydrate=fail
    with pytest.raises(SessionQueryError) as caught:await reader.read('cold')
    assert caught.value.code=='SESSION_QUERY_CORRUPT_SESSION'
    lease=await reader.read('cold',dict(projectionMode='none'));lease.dispose()
    ctx.get('sessions').create('cold');registry.snapshot=fail
    with pytest.raises(SessionQueryError,match='failed to project session') as caught:
        await reader.read('cold')
    assert caught.value.code=='SESSION_QUERY_CORRUPT_SESSION'
    assert isinstance(caught.value.cause,RuntimeError) and str(caught.value.cause)=='projection'


@pytest.mark.parametrize('compression',['none','zstd'])
@pytest.mark.asyncio
async def test_real_backend_cold_observation_does_not_repair_durable_log(tmp_path,compression):
    root=Context();await root.plugin(CurrentSessionPlugin)
    p=CurrentJsonlSessionPersistence(str(tmp_path/'logs'),compression)
    root.set_service('sessionPersistence',p)
    h=await p.create(header());await h.append(events());await h.close()
    before={str(f):f.read_bytes() for f in (tmp_path/'logs').rglob('*') if f.is_file()}
    reader=CurrentSessionObservationReader(root)
    lease=await reader.read('cold')
    assert lease.cursor==1 and lease.events[-1]['data']['reason']['kind']=='interrupted'
    assert not root.get('sessions').list()
    lease.dispose()
    after={str(f):f.read_bytes() for f in (tmp_path/'logs').rglob('*') if f.is_file()}
    assert before==after
    await p.tracker.dispose()
    await root.fiber.dispose()
