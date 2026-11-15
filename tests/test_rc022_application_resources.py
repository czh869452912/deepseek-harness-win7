import pytest
from dsh.cordis import Context
from dsh.typert.current import CurrentTypertRegistry
from dsh.typert.access import call_resources
from dsh.core.abort import NEVER_ABORTED
from dsh.api.session_resource import register_session_resource
from scripts.rc022_application_resources_probe import observe


@pytest.mark.asyncio
async def test_real_application_resource_admission_and_effects(tmp_path):
    rows={row['name']:row for row in await observe(tmp_path)}
    assert len(rows)==27
    assert rows['reader:1']==dict(name='reader:1',value='a',absent=False)
    assert rows['reader:4']['value']=='b'
    assert rows['reader:5']['absent'] and rows['reader:9']['absent']
    assert rows['reader:11']['error']=='coexisting'
    for name in ('wrong-parent-grant','preset-denied','interrupt-denied'):
        assert rows[name]['error']['code']=='remote-access/denied'
        assert rows[name]['lookupCount']==rows[name]['messages']==0
        assert not rows[name]['parentChanged']
    assert rows['target-grant']['value']==dict(accepted=True)
    assert rows['target-grant']['messages']==1
    assert rows['attribution']['source']['principal']==dict(kind='guest',id='g')
    assert rows['preset-allowed']['value']=='coding'
    assert rows['preset-allowed']['lookupCount']==1
    assert rows['interrupt-allowed']['value']==dict(accepted=True)


@pytest.mark.asyncio
async def test_registered_session_resource_rejects_ambiguity_and_invalid_identity_then_retires():
    ctx=Context()
    try:
        await ctx.plugin(CurrentTypertRegistry)
        child=ctx.extend()
        dispose=register_session_resource(child)
        descriptor=dict(invocation=dict(kind='direct'),parameters=[dict(name='request',wire='request',source='json')])
        def read(request): return call_resources(ctx.typert,None,descriptor,dict(request=request),NEVER_ABORTED)
        assert read(dict(address=dict(kind='session',sessionId='shared')))==[dict(kind='session',id='shared')]
        assert read(dict(address=dict(kind='subagent',parentSessionId='parent',childSessionId='child')))==[dict(kind='session',id='child')]
        for request in (dict(sessionId='shared',address=dict(kind='session',sessionId='other')),dict(sessionId=[]),dict(sessionId=''),dict(sessionId=3),dict(address=None)):
            assert read(request) is None
        assert read({})==[dict(kind='global')]
        dispose()
        assert ctx.typert.resources.get('session') is None
    finally: await ctx.fiber.dispose()
