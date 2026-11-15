import pytest
from scripts.rc022_archive_probe import observe

@pytest.mark.asyncio
async def test_archive_turn_admission_and_resource_declarations():
    rows={row['action']:row for row in await observe()}
    assert rows['states']['running']==[dict(kind='turn'),dict(kind='probe')]
    for key in ('idle','unknown','detached'):assert rows['states'][key]==[dict(kind='probe')]
    assert rows['running-to-idle']['result']==[dict(kind='turn'),dict(kind='probe')]
    assert not rows['running-to-idle']['same']
    assert rows['idle-to-running']['result']==[dict(kind='probe')] and rows['idle-to-running']['same']
    assert rows['stop']['calls']==[[dict(kind='user'),None]] and rows['stop']['notAwaited'] and rows['stop']['afterIdle']==1
    assert not rows['stop-throws']['same'] and rows['stop-throws']['contained'] and rows['stop-throws']['count']==1
    assert rows['dispose']['before']==[dict(kind='turn')] and rows['dispose']['after']==[] and rows['dispose']['calls']==[]
    for key in ('types-before','types-after'):
        row=rows[key]
        assert row['lookup']['resource']==row['context']['resource']=='session'
        assert row['resolved'] and row['scoped'] and row['unknown'] and row['withdrawn']

@pytest.mark.asyncio
async def test_previous_registry_has_no_archive_provider_or_resource_declaration():
    from dsh.cordis import Context
    from dsh.core.agent_current import CurrentAgentRegistry
    ctx=Context()
    try:
        service=CurrentAgentRegistry(ctx)
        assert 'resource' not in service._host_lookup_provider()
        assert 'resource' not in service._host_context_adapter()
        assert await ctx.waterfall('workspace/session-activity',dict(sessionId='missing'),lambda:[])==[]
    finally:await ctx.fiber.dispose()
