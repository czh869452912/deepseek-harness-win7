from types import SimpleNamespace as NS

import pytest

from dsh.cordis.plugin import Plugin
from dsh.cordis.volatile import create_volatile
from dsh.core.session.current_session import CurrentSession
from dsh.interaction.permission_current import CurrentPermissionPresets
from scripts import rc022_permission_catalog_probe as probe
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_live_catalog_current_only_projection_and_auto_gate_lifecycle():
    rows={row['name']:row for row in await probe.observe()}
    assert len(rows)==17
    assert rows['initial']['selection']['wire']==dict(permissions=dict(currentValue='workspace-write'))
    assert [item['type'] for item in rows['created']['selection']['events']]==['permission/preset','sandbox/mode','approval/policy']
    assert rows['shared-bundle']['selection']['current']=='same'
    assert len(rows['shared-bundle']['selection']['events'])==4
    assert rows['registered']['catalog']['options'][-1]==dict(value='auto',name='auto')
    assert all(item['value']!='auto' for item in rows['registered']['catalog']['defaultOptions'])
    assert rows['auto-selected']['admissions']==['admitted','admitted']
    assert rows['delegated-never']['selection']['current']=='auto'
    assert rows['restored-live']['admissions']==['admitted']*3
    assert rows['unregistered']['selection']['current']=='danger-full-access'
    assert rows['registered']['notifications']==1 and rows['unregistered']['notifications']==2
    assert rows['restore-refused']['unchanged'] and rows['admission-refused']['unchanged']
    assert rows['custom']['selection']['wire']==dict(permissions=dict(currentValue='custom'))
    assert rows['unload']==dict(name='unload',service=False,wire={})


@pytest.mark.asyncio
async def test_actual_agent_creation_restore_admission_and_runtime_policy_consumer(tmp_path):
    from dsh.sandbox.policy_current import CurrentSandboxPolicy
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx
    ctx.set_service('shell',NS(sandboxMode='workspace-write'))
    ctx.set_service('approval',NS(config=dict(policy='ask')))
    await ctx.plugin(CurrentSandboxPolicy,dict(mode='workspace-write'))
    owner=await ctx.plugin(CurrentPermissionPresets);leases=[]
    async def create(identity,**args):
        lease=await ctx.agents.create(dict(sessionId=identity,agentOptions=dict(provider='script',model='model'),**args));leases.append(lease);return lease.agent
    try:
        agent=await create('root');session=agent.session
        assert ctx.permissionPresets.current(session)=='workspace-write'
        assert ctx.sandboxPolicy.resolve(dict(session=session))['mode']=='workspace-write'
        admissions=[]
        class Auto(Plugin):
            inject=['permissionPresets']
            def apply(self,scope):scope.permissionPresets.registerAuto(lambda:admissions.append(True))
        auto=await ctx.plugin(Auto)
        ctx.permissionPresets.set(session,'auto')
        assert ctx.sandboxPolicy.resolve(dict(session=session))['mode']=='danger-full-access'
        seed=session.snapshotEvents()
        restored=await create('restored',seed=seed)
        assert ctx.permissionPresets.current(restored.session)=='auto' and len(admissions)==2
        await auto.dispose()
        with pytest.raises(Exception,match='cannot restore preset "auto"'):
            await create('refused',seed=seed)
        assert ctx.agents.get('refused') is None
        assert ctx.permissionPresets.current(session)=='custom'
        await owner.dispose()
        assert 'permissions' not in ctx.sessionProjections.snapshot(session)['values']
    finally:
        for lease in reversed(leases):await lease.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_live_default_is_configured_table_only_and_does_not_rewrite_existing(tmp_path):
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx
    ctx.set_service('shell',NS(sandboxMode='workspace-write'));ctx.set_service('approval',NS(config=dict(policy='ask')))
    # Service constructor supports the same volatile reference the Loader supplies.
    reference=create_volatile('workspace-write')
    service=CurrentPermissionPresets(ctx,dict(defaultPreset=reference))
    try:
        await service.init()
        first=CurrentSession.create('first',format_version=4);service.pin_initial_permission(first)
        reference._write('danger-full-access')
        second=CurrentSession.create('second',format_version=4);service.pin_initial_permission(second)
        assert service.current(first)=='workspace-write' and service.current(second)=='danger-full-access'
        reference._write('auto')
        with pytest.raises(Exception,match='unknown default preset "auto"'):service.catalog()
        reference._write('workspace-write')
        assert service.catalog()['defaultPreset']=='workspace-write'
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('reserved',['custom','auto'])
async def test_reserved_configured_presets_rejected_before_any_session_effect(tmp_path,reserved):
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx
    ctx.set_service('shell',NS(sandboxMode='workspace-write'));ctx.set_service('approval',NS(config=dict(policy='ask')))
    try:
        with pytest.raises(Exception,match='reserved'):
            await ctx.plugin(CurrentPermissionPresets,dict(presets={reserved:dict(sandbox='workspace-write',approval='ask')}))
        assert ctx.get('permissionPresets') is None
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_catalog_remote_marker_and_settings_presentation_release(tmp_path):
    from dsh.typert.remote import remote_methods
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx;effects=[]
    ctx.set_service('shell',NS(sandboxMode='workspace-write'));ctx.set_service('approval',NS(config=dict(policy='ask')))
    def configure(presentation,owner):
        effects.append(dict(presentation=presentation,owner=owner))
        return lambda:effects.append('released')
    ctx.set_service('settings',NS(configure=configure))
    try:
        owner=await ctx.plugin(CurrentPermissionPresets)
        assert effects[0]['presentation']==dict(auto=False)
        assert ctx.permissionPresets.typertRemote['namespace']=='permissionPresets'
        methods=remote_methods(ctx.permissionPresets)
        assert methods==[dict(invocation=dict(kind='direct'),method='catalog')]
        await owner.dispose()
        assert effects[-1]=='released'
    finally:await ctx.fiber.dispose()
