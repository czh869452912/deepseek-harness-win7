from types import SimpleNamespace as NS
import pytest
from scripts.rc022_archive_admission_probe import observe


@pytest.mark.asyncio
async def test_archive_fanout_and_ancestry_boundaries():
    rows={row['action']:row for row in await observe()}
    assert [item['id'] for item in rows['headers']['activity'][0]['items']]==['parent','child']
    assert rows['inherited-label']['activity'][0]['items'][1]==dict(id='child')
    assert rows['ordinary-fork']['decision']==dict(kind='enter')
    assert rows['offline']['decision']==dict(kind='enter')
    assert rows['stop-failure']['trace']==['parent','warning','child']
    assert rows['no-workspace']['decision']==dict(kind='enter')


@pytest.mark.asyncio
async def test_actual_cordis_archive_hooks_disappear_with_owner():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.subagent.archive_admission import install_subagent_archive_admission
    ctx=Context();store=CurrentSessionStore(ctx,4);cancelled=[]
    child=NS(id='child',status='running',session=store.create('child',dict(meta=dict(origin='subagent',parentSession='offline'))),
             cancel=lambda reason:cancelled.append(reason))
    ctx.set_service('agents',NS(list=lambda:[child],get=lambda identity:child if identity=='child' else None))
    ctx.set_service('workspaceRegistry',NS(archivedSessionIds=['root']))
    class Admission(Plugin):
        def apply(self,scope):
            install_subagent_archive_admission(scope,lambda agent:['root','offline'],lambda session:None)
    try:
        owner=await ctx.plugin(Admission)
        assert await ctx.waterfall('workspace/session-activity',dict(sessionId='root'),lambda:[])==[
            dict(kind='subagent',items=[dict(id='child')])]
        assert await ctx.waterfall('agent/pre-step',dict(agent=child),lambda:dict(kind='enter'))==dict(kind='reject')
        ctx.emit('workspace/session-stop',dict(sessionId='root'))
        assert cancelled==[dict(kind='parent')]
        await owner.dispose()
        assert await ctx.waterfall('workspace/session-activity',dict(sessionId='root'),lambda:[])==[]
        assert await ctx.waterfall('agent/pre-step',dict(agent=child),lambda:dict(kind='enter'))==dict(kind='enter')
    finally:await ctx.fiber.dispose()
