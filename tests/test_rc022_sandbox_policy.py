import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.sandbox.policy_current import CurrentSandboxPolicy,set_sandbox_mode
from dsh.session.projections import SessionProjectionRegistry
from dsh.shell.sandbox_current import CurrentSandboxPwshExecutor
from dsh.shell.tool_current import CurrentToolPwsh
from scripts import rc022_sandbox_policy_probe as probe
from scripts.rc022_subagent_fixture import setup


class Projections(Plugin):
    def apply(self,ctx):SessionProjectionRegistry(ctx,4)


@pytest.mark.asyncio
async def test_real_sessions_projection_prompt_and_exact_effect_lifetimes():
    rows=await probe.observe();by_name={row['name']:row for row in rows}
    assert by_name['default']['value']['workspaceRoot']=='C:/fallback/../root'
    assert by_name['default']['first']['workspaceRoot']=='C:/workspace/../first'
    assert by_name['grant']['granted']['additionalWritableRoots']==['C:/shared//root','C:/memory']
    assert by_name['grant']['before']['additionalWritableRoots']==['C:/shared//root']
    assert by_name['grant']['resumed']['additionalWritableRoots']==['C:/shared//root']
    assert by_name['duplicate-owned']['value']['additionalWritableRoots']==['C:/shared//root','C:/memory']
    assert by_name['child-owned']['value']['additionalWritableRoots']==['C:/shared//root','C:/child-grant']
    assert by_name['child-disposed']['value']['additionalWritableRoots']==['C:/shared//root']
    assert 'On Windows, these additional grants apply to file tools only' in by_name['workspace-context']['value'][0]['text']
    assert 'C:/prompt-extra' not in by_name['read-only']['context'][0]['text']
    assert by_name['full']['approved']['mode']=='workspace-write'
    assert by_name['resumed']['value']['mode']=='danger-full-access' and by_name['resumed']['value']['additionalWritableRoots']==['C:/shared//root']
    assert not by_name['unload']['service'] and by_name['unload']['context']==[]
    invalid=[row for row in rows if row['name']=='invalid-session']
    assert invalid[0]['error']['code'] is None and invalid[1]['error']['code']=='SANDBOX_INVALID_ROOT'


@pytest.mark.asyncio
@pytest.mark.parametrize('config',[dict(mode='invalid'),dict(workspaceRoot='relative'),dict(workspaceRoot='C:/bad\0root'),dict(additionalWritableRoots=['relative']),dict(additionalWritableRoots=['C:/bad\0root'])])
async def test_invalid_config_fails_before_available_service(config):
    ctx=Context();await ctx.plugin(Projections)
    try:
        with pytest.raises(Exception):await ctx.plugin(CurrentSandboxPolicy,config)
        assert ctx.get('sandboxPolicy') is None
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_schema_defaults_and_frozen_detached_grants(tmp_path):
    ctx=Context();await ctx.plugin(Projections);await ctx.plugin(CurrentSandboxPolicy)
    try:
        assert ctx.sandboxPolicy.defaultMode=='read-only'
        assert ctx.sandboxPolicy.additionalWritableRoots is None
        assert 'additionalWritableRoots' not in ctx.sandboxPolicy.resolve()
    finally:await ctx.fiber.dispose()
    ctx=Context();await ctx.plugin(Projections);roots=[str(tmp_path)];await ctx.plugin(CurrentSandboxPolicy,dict(additionalWritableRoots=roots));roots.append('C:/foreign')
    try:
        resolved=ctx.sandboxPolicy.resolve()
        assert resolved['additionalWritableRoots']==[str(tmp_path)]
        with pytest.raises(TypeError):resolved['additionalWritableRoots'].append('C:/foreign')
        assert ctx.sandboxPolicy.resolve()['additionalWritableRoots']==[str(tmp_path)]
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_current_tool_and_confined_executor_resolve_policy_at_each_operation(tmp_path):
    fixture=await setup(tmp_path,script=[]);ctx=fixture.ctx;policies=[]
    empty=NS(readFrom=lambda _:dict(text='',nextOffset=0,lossy=False))
    def spawn(_):
        future=asyncio.get_running_loop().create_future();future.set_result(dict(exitCode=0,signal=None))
        return NS(done=future,collected=dict(stdout=empty,stderr=empty),terminate=lambda:None)
    async def confine(argv,policy,signal):
        policies.append(policy);return dict(argv=argv,enforcement='partial',denialSignatures=[],runnerFailureRules=[])
    ctx.set_service('subprocess',NS(spawn=spawn));ctx.set_service('sandbox',NS(confine=confine));ctx.set_service('shellEnv',NS(collect=lambda _:{}))
    await ctx.plugin(CurrentSandboxPolicy,dict(additionalWritableRoots=['C:/shared']))
    await ctx.plugin(CurrentSandboxPwshExecutor)
    await ctx.plugin(CurrentToolPwsh)
    lease=await ctx.agents.create(dict(sessionId='policy-owner',meta=dict(cwd='C:/session/../root'),agentOptions=dict(provider='script',model='model')))
    try:
        async def call():return await ctx.tools.execute(ToolExecutionInput('call','pwsh',dict(command='controlled',description='Run controlled policy probe'),agent=lease.agent,signal=NEVER_ABORTED))
        first=await call();assert not first.is_error and first.value['sandbox']['mode']=='read-only'
        old=policies[0];remove=ctx.sandboxPolicy.registerWritableRoot(lease.agent.session,'C:/dynamic')
        set_sandbox_mode(lease.agent.session,'workspace-write')
        second=await call();assert not second.is_error and second.value['sandbox']['mode']=='workspace-write'
        assert old['mode']=='read-only' and old['additionalWritableRoots']==['C:/shared']
        assert policies[1]==dict(mode='workspace-write',workspaceRoot='C:/session/../root',sessionId='policy-owner',additionalWritableRoots=['C:/shared','C:/dynamic'])
        remove();assert ctx.sandboxPolicy.resolve(dict(session=lease.agent.session))['additionalWritableRoots']==['C:/shared']
    finally:await lease.dispose();await ctx.fiber.dispose()
