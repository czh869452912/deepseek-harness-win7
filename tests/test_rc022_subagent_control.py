import pytest
from scripts.rc022_subagent_control_probe import observe


@pytest.mark.asyncio
async def test_target_only_control_errors_and_real_delivery(tmp_path):
    rows=await observe(tmp_path)
    assert len(rows)==40
    rejects=[row for row in rows if row['kind']=='rejection']
    assert all(row['cause'] for row in rejects)
    assert rejects[3]['value']['message']=='subagent membership in the active tree could not be verified'
    assert rejects[6]['value']['code']=='subagent/delivery-unavailable'
    deliveries={row['name']:row for row in rows if row['kind']=='delivery'}
    assert all(row['accepted'] for row in deliveries.values())
    assert 'principal' not in deliveries['queue']['message']['source']
    assert deliveries['steer']['message']['source']['principal']==dict(kind='test-guest',guest='g1')
    assert deliveries['cold']['message']['source']['rpcId']=='rpc-cold'
    assert deliveries['cold']['message']['content']==[dict(type='text',text='cold')]
    interrupts=[row for row in rows if row['kind']=='interrupt']
    assert [row['value'] for row in interrupts[:2]]==[dict(accepted=True)]*2
    assert interrupts[-1]['value']['code']=='gateway/bad-request'


@pytest.mark.asyncio
async def test_cold_prompt_capacity_refusal_has_actionable_remote_code(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.cordis.volatile import WRITE
    from dsh.typert.remote import RemoteError
    fixture=await setup(tmp_path);ctx=fixture.ctx;service=fixture.service
    try:
        root=(await ctx.agents.create(dict(sessionId='root',agentOptions=dict(provider='script',model='model')))).agent
        async def child(identity):
            return await service.startActivation(dict(provider='spawn',parent=root,childId=identity,name=identity,label='Task',
                prompt=[dict(type='text',text='Task')],signal=fixture.signal,delivery='caller'))
        old=await child('cold');await old['dispose']()
        await child('active')
        getattr(service.config['maxActiveSubagents'],WRITE)(1)
        with pytest.raises(RemoteError) as captured:
            await service.prompt(dict(requestId='rpc-capacity',childSessionId='cold',delivery='queue',content=[dict(type='text',text='continue')]),fixture.signal)
        assert captured.value.code=='subagent/delivery-unavailable'
        assert ctx.agents.get('cold') is None
        assert ctx.agents.get('active') is not None
    finally:await ctx.fiber.dispose()


def test_principal_owner_omission_and_remote_binding_remains_deferred():
    from dsh.typert.principal import principal_of
    from dsh.core.session.json import UNDEFINED
    from dsh.typert.remote import remote_methods
    from dsh.subagent.service import SubagentRuntime
    assert principal_of(None) is UNDEFINED
    assert principal_of(dict(peer=dict(principal=dict(kind='owner')))) is UNDEFINED
    guest=dict(kind='guest',id='g')
    assert principal_of(dict(peer=dict(principal=guest))) is guest
    assert not any(row['method'] in ('prompt','interruptByUser') for row in remote_methods(SubagentRuntime))


@pytest.mark.asyncio
async def test_invocation_accessor_is_root_owned_and_metadata_shadows_it():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.typert.remote import TypertRemoteService,bind_typert_remote
    class Mounted(Plugin):
        def apply(self,ctx):TypertRemoteService(ctx,'one')
    ctx=Context()
    try:
        owner=await ctx.plugin(Mounted)
        assert ctx.invocation is None
        accessor=ctx.reflect.props['invocation']
        TypertRemoteService(ctx,'two')
        assert ctx.reflect.props['invocation'] is accessor
        invocation=dict(peer=dict(principal=dict(kind='guest')))
        assert ctx.extend(dict(invocation=invocation)).invocation is invocation
        await owner.dispose()
        assert ctx.invocation is None and ctx.reflect.props['invocation'] is accessor
        bind_typert_remote(object(),'plain')
    finally:await ctx.fiber.dispose()
    assert 'invocation' not in ctx.reflect.props
