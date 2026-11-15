import pytest
from scripts.rc022_title_probe import observe,input_schema_cases,result_cases

@pytest.mark.asyncio
async def test_v4_title_input_and_provider_lifecycle():
    rows=await observe()
    assert len(rows)==123+len(input_schema_cases())+len(result_cases())
    for row in rows:
        if 'action' not in row:continue
        assert row['input']['ver']==3
        assert 'title' in row['summary'] and 'titleInput' not in row['summary']
        assert row['input']['val']['first']['seq']>=0
        if row['action'].startswith('activation-'):
            assert row['hidden'] and row['input']['val']['count']==2 and len(row['titleEvents'])==1
        if row['action']=='watermark':
            request=row['requests'][0]
            assert len(request['messages'])==1 and request['currentTitle']['eventSeq']>request['messages'][0]['seq']
            assert row['input']['val']['count']==2
        if row['action']=='replacement':
            assert row['draining'] and row['title']['source']['provider']=='replacement'
            assert 'disposed' in row['oldError']
        if row['action']=='rename-queued':assert row['title']['title']=='Pinned' and len(row['titleEvents'])==1
        if row['action'].startswith('eligibility-'):
            assert len(row['requests'])==(0 if row['action'] in ('eligibility-seeded','eligibility-subagent') else 1)

@pytest.mark.asyncio
async def test_v4_session_listener_runs_prefix_before_next_observer_and_batch_member():
    import asyncio
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.core.session.json import UNDEFINED
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    ctx=Context();seen=[];gate=asyncio.Event();done=asyncio.Event();tails=[]
    try:
        await ctx.plugin(Store);session=ctx.get('sessions').create('prefix')
        async def listener(subject,event):
            seen.append(('prefix',event['seq'],subject.seq,subject.currentBatchPublication is event))
            with pytest.raises(ValueError,match='reenter'):subject.append('turn/start',dict(turn=99))
            await gate.wait();tails.append(subject.currentBatchPublication is UNDEFINED)
            if len(tails)==2:done.set()
        ctx.on('session/event',listener);ctx.on('session/event',lambda subject,event:seen.append(('later',event['seq'])))
        session.append([['turn/start',dict(turn=1)],['turn/end',dict(turn=1)]])
        assert seen==[('prefix',0,2,True),('later',0),('prefix',1,2,True),('later',1)]
        assert not tails;gate.set();await asyncio.wait_for(done.wait(),1);assert tails==[True,True]
    finally:gate.set();await ctx.fiber.dispose()
