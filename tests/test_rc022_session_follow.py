from types import SimpleNamespace as NS
import pytest
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader
from dsh.api.session_web_authorized import SessionWebController
from dsh.typert.remote import RemoteError
from scripts.rc022_session_follow_probe import observe


@pytest.mark.asyncio
async def test_opening_race_mixed_frames_and_explicit_retained_promotion(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert len(rows)==7
    opening=rows['live-opening']
    assert opening['value']['cursor']==0 and opening['leaseReleased'] and opening['promotions']==[]
    assert opening['value']['assistantStream']['revision']==2
    frames=rows['uncovered-mixed']['values']
    assert [frame['type'] for frame in frames]==['event','assistant-stream','event']
    assert [frame['event']['seq'] for frame in frames if frame['type']=='event']==[1,2]
    assert frames[1]['frame']['type']=='end'
    assert rows['cold-default-passive']['agentAbsent'] and rows['cold-default-passive']['leaseReleased']
    assert rows['cold-default-passive']['promotions']==[]
    assert rows['promotion-before-opening']['promotions']==['follow']
    assert rows['promotion-before-opening']['leaseReleased']
    assert rows['promotion-outlives-consumer']['attached']
    assert rows['missing-subagent']['code']=='subagent/not-found'


def lease_fixture():
    states=dict(opening=False,promotion=False)
    retained=NS(dispose=lambda:states.update(promotion=True))
    observation=NS(header=SessionHeader('target',cwd='C:/follow',version=4),cursor=-1,events=[],inheritedEventCount=0,
        projections=dict(asOfSeq=-1,values={}),source='prepared',retain=lambda:retained,
        dispose=lambda:states.update(opening=True))
    async def using(*_):return observation
    return NS(usingObservation=using),observation,retained,states


@pytest.mark.asyncio
async def test_promotion_failure_releases_retained_lease_before_any_opening():
    ctx=Context();abort=AbortController();history,observation,retained,states=lease_fixture();primary=RuntimeError('promotion rejected')
    def promote(value):
        assert value is retained and states['opening']
        raise primary
    web=SessionWebController(ctx,history,promote)
    source=web.follow(dict(address=dict(kind='session',sessionId='target'),activate=True),abort.signal)
    try:
        with pytest.raises(RuntimeError) as failure:await source.__anext__()
        assert failure.value is primary and states==dict(opening=True,promotion=True)
        assert abort.signal._dom_listeners=={}
    finally:await source.aclose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_projection_failure_releases_opening_without_promoting():
    ctx=Context();abort=AbortController();history,observation,_,states=lease_fixture();observation.projections=None;promoted=[]
    web=SessionWebController(ctx,history,lambda value:promoted.append(value))
    source=web.follow(dict(address=dict(kind='session',sessionId='target'),activate=True),abort.signal)
    try:
        with pytest.raises(RemoteError) as failure:await source.__anext__()
        assert failure.value.code=='session/projections-unavailable'
        assert states==dict(opening=True,promotion=False) and promoted==[]
        assert abort.signal._dom_listeners=={}
    finally:await source.aclose();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_snapshot_only_consumer_releases_listeners_but_transfers_promotion_lease():
    ctx=Context();abort=AbortController();history,_,retained,states=lease_fixture();promoted=[]
    web=SessionWebController(ctx,history,lambda value:promoted.append(value))
    source=web.follow(dict(address=dict(kind='session',sessionId='target'),activate=True),abort.signal)
    try:
        assert (await source.__anext__())['type']=='snapshot'
        assert promoted==[retained] and states==dict(opening=True,promotion=False)
        await source.aclose()
        assert abort.signal._dom_listeners=={} and not states['promotion']
        retained.dispose();assert states['promotion']
    finally:await source.aclose();await ctx.fiber.dispose()
