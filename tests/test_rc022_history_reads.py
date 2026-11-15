import asyncio
from types import SimpleNamespace as NS
import pytest
from dsh.api.session_history_authorized import SessionHistoryReads, resolve_history_request, validate_observation_address, paginate
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.session import SessionHeader
from dsh.cordis.errors import ThrownValueError
from dsh.session.session_query import SessionQueryError
from dsh.typert.remote import RemoteError
from scripts.rc022_history_reads_probe import observe


@pytest.mark.asyncio
async def test_passive_history_exact_cut_and_header_only_cache(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert len(rows)==22
    assert rows['default-cut']['value']['cursor']==17
    assert rows['fixed-cut']['value']['cursor']==11
    assert rows['empty-cut']['value']==dict(cursor=-1,records=[],hasMore=False)
    assert rows['turn-window']['value']['records'][0]['event']['seq']==6
    assert rows['assistant-output']['value']['truncated']
    assert not rows['assistant-interval']['value']['truncated']
    assert rows['cold-projections']['agentAbsent'] and rows['cold-projections']['reads']==1
    assert rows['missing-projections']['value'] is None
    assert not rows['seeded-header-cache']['wrongCutSeeds']
    assert rows['seeded-header-cache']['value']==dict(asOfSeq=9,values=dict(title='Seeded title'))
    assert rows['predecessor-title']['current'] is None
    assert rows['predecessor-title']['predecessor']['asOfSeq']==9
    assert rows['migration-hints']['value']==dict(kind='migration-required',values=dict(title='Seeded title'))
    assert rows['migration-hints']['reads']==0 and rows['passive']['agents']==0


@pytest.mark.parametrize('window_request',[
    dict(throughSeq=True),dict(throughSeq=-0.0),dict(throughSeq=-2),dict(throughSeq=9007199254740992),
    dict(beforeSeq=-0.0),dict(beforeSeq=False),dict(maxMessages=0),dict(maxMessages=float('nan')),
    dict(turnWindow=dict(minMessages=1,minTurns=False)),dict(turnWindow=dict(minMessages=51,minTurns=1)),
])
def test_invalid_windows_fail_before_observation(window_request):
    with pytest.raises(RemoteError) as failure: resolve_history_request(window_request)
    assert failure.value.code=='gateway/bad-request'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected',[
    ('missing',None),('query-aborted','gateway/cancelled'),('opaque-aborted','gateway/cancelled'),
    ('internal','gateway/internal'),('remote','custom/read'),
])
async def test_projection_failure_taxonomy(kind,expected):
    primary=(SessionQueryError('missing','SESSION_QUERY_SESSION_NOT_FOUND') if kind=='missing' else
             SessionQueryError('query cancelled','SESSION_QUERY_ABORTED') if kind=='query-aborted' else
             ThrownValueError(dict(code='SESSION_QUERY_ABORTED')) if kind=='opaque-aborted' else
             RemoteError('custom/read','custom',{}) if kind=='remote' else RuntimeError('broken storage'))
    async def stat(*_):raise primary
    services=dict(sessions=NS(get=lambda _:None),sessionPersistence=NS(stat=stat))
    history=SessionHistoryReads(NS(get=services.get))
    if expected is None:
        assert await history.projections(dict(sessionId='target'),NEVER_ABORTED) is None
    else:
        with pytest.raises(RemoteError) as failure:await history.projections(dict(sessionId='target'),NEVER_ABORTED)
        assert failure.value.code==expected
        assert failure.value is primary if kind=='remote' else failure.value.cause is primary


@pytest.mark.asyncio
async def test_borrowed_observation_lives_until_async_callback_and_disposes_on_task_cancel():
    disposed=[];entered=asyncio.Event();gate=asyncio.Event()
    observation=NS(dispose=lambda:disposed.append(True))
    async def observe(*_):return observation
    history=SessionHistoryReads(NS(get=lambda _:NS(observeSession=observe)))
    async def callback(value):
        assert value is observation
        entered.set();await gate.wait()
    task=asyncio.ensure_future(history.usingObservation(dict(sessionId='target',projection=True),NEVER_ABORTED,callback))
    await entered.wait();assert disposed==[]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert disposed==[True]
    transferred=await history.usingObservation(dict(sessionId='target',projection=False),NEVER_ABORTED)
    assert transferred is observation and disposed==[True]
    transferred.dispose();assert disposed==[True,True]


@pytest.mark.asyncio
async def test_return_race_disposes_lease_and_opaque_cancel_uses_fallback_message():
    controller=AbortController();disposed=[]
    async def observe(*_):
        controller.abort();return NS(dispose=lambda:disposed.append(True))
    history=SessionHistoryReads(NS(get=lambda _:NS(observeSession=observe)))
    with pytest.raises(Exception):await history.usingObservation(dict(sessionId='target',projection=False),controller.signal)
    assert disposed==[True]
    async def opaque(*_):raise ThrownValueError(dict(code='SESSION_QUERY_ABORTED'))
    history=SessionHistoryReads(NS(get=lambda _:NS(observeSession=opaque)))
    with pytest.raises(RemoteError) as failure:
        await history.events(dict(address=dict(kind='session',sessionId='target')),NEVER_ABORTED)
    assert failure.value.code=='gateway/cancelled' and failure.value.message=='Session read was cancelled'


def test_unknown_subagent_mode_still_checks_durable_parent_and_descriptor():
    address=dict(kind='subagent',parentSessionId='parent',childSessionId='child',mode='unknown')
    observation=NS(header=SessionHeader('child',cwd='C:/work',origin='subagent',parent_session='parent'),inheritedEventCount=3,
        projections=dict(values=dict(subagent=dict(seq=3,mode='continuable'))))
    validate_observation_address(address,observation)
    for changed,code in [(dict(mode='external'),'subagent/unauthorized'),(dict(parentSessionId='other'),'subagent/unauthorized')]:
        with pytest.raises(RemoteError) as failure:validate_observation_address(dict(address,**changed),observation)
        assert failure.value.code==code
    observation.projections=dict(values=dict(subagent=None))
    with pytest.raises(RemoteError) as failure:validate_observation_address(address,observation)
    assert failure.value.code=='subagent/catalog-diagnostic'


def test_history_pagination_keeps_message_source_group_and_ignores_replacement_budget():
    events=[dict(seq=0,type='turn/start'),dict(seq=1,type='fixture/note'),dict(seq=2,type='assistant/message',surfaceOp='append',sourceEventSeqs=[1]),
            dict(seq=3,type='user/message',surfaceOp=dict(op='replace',startSeq=2,endSeq=2)),dict(seq=4,type='turn/end')]
    selected,more=paginate(events,None,1,4)
    assert [event['seq'] for event in selected]==[1,2,3,4] and more
