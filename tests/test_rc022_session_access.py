import pytest
from types import SimpleNamespace as NS
from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.api.session_authorized import ProjectionSessionControl
from scripts.rc022_session_access_probe import observe


@pytest.mark.asyncio
async def test_session_read_filtering_and_live_projection_frames(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert len(rows)==11
    assert [row['sessionId'] for row in rows['owner-list']['value']['items']]==['hidden','shared']
    assert [row['sessionId'] for row in rows['guest-list']['value']['items']]==['shared']
    assert rows['guest-search']['value']==dict(items=[dict(sessionId='shared',snippet='Shared')],hasMore=True)
    assert rows['global-refusal']==dict(name='global-refusal',code='remote-access/denied',reads=0)
    assert rows['owner-baseline']['value']['keys']==['hidden','shared']
    assert rows['guest-baseline']['value']['keys']==['shared']
    assert [row['sessionId'] for row in rows['owner-updates']['value']]==['hidden','shared']
    assert rows['guest-update']['value']['sessionId']=='shared'
    assert rows['changed-grant']['value']['sessionId']=='hidden'
    assert rows['changed-grant']['value']['changes']==[dict(key='accessProbe',val=4)]
    assert rows['cancelled']['ended']==[dict(error='gateway/cancelled')]*2
    assert rows['cancelled']['subscriptions']==0


@pytest.mark.asyncio
async def test_projection_control_drains_accepted_frames_on_close_and_releases_listener():
    ctx=Context();listeners=[]
    def subscribe(callback):
        listeners.append(callback)
        return ctx.effect(lambda:lambda:listeners.remove(callback))
    session=NS(id='session')
    ctx.set_service('sessions',NS(list=lambda:[session]))
    ctx.set_service('sessionProjections',NS(onEventChanged=subscribe,snapshot=lambda _:dict(asOfSeq=0,values=dict(value=1))))
    control=ProjectionSessionControl(ctx);abort=AbortController();stream=control.control(abort.signal)
    try:
        assert await stream.__anext__()==dict(type='baseline',value=dict(projections=dict(session=dict(asOfSeq=0,values=dict(value=1)))))
        listeners[0](session,[dict(key='value',val=2),dict(key='other',val=3)],1)
        control.close()
        assert await stream.__anext__()==dict(type='projection',sessionId='session',seq=1,changes=[dict(key='value',val=2),dict(key='other',val=3)])
        with pytest.raises(StopAsyncIteration):await stream.__anext__()
        assert not control.streams
    finally:
        await stream.aclose();await ctx.fiber.dispose()
    assert not listeners
