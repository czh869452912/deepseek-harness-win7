"""Assertion ports of pinned agent-presets mount/invariant specs.

Parameter IDs are upstream source lines, not locally invented completion counts.
Node absolute-file-URL import is adapted to Python absolute file import.
"""
import asyncio
from types import SimpleNamespace

import pytest
import pytest_asyncio
import yaml

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.scope import ScopeKey, bind_scope_parent, create_scope, scope_of
from dsh.core.session import SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.diagnostics.invariants import InvariantRegistry, InvariantError
from dsh.presets import AgentPresets, PresetMountError, live_preset_mounts, leaked_services
from dsh.presets.invariant import AgentPresetsInvariantPlugin
from test_agent_presets_upstream_parity import seed


@pytest_asyncio.fixture
async def harness(tmp_path):
    ctx = Context()
    ctx.baseUrl = str(tmp_path)
    await ctx.plugin(Loader)
    for plugin in (SessionPlugin, SystemPrompt, ToolsPlugin, AgentPlugin, AgentLoopPlugin):
        await ctx.plugin(plugin)

    def contribute(c, config):
        label = config['label']
        c.get('tools').register_tool(name=label, description=label, parameters={'type':'object'}, handler=lambda args: label)
        c.get('systemPrompt').section({'name':'preset:'+label,'order':0,'text':label})
    def refuses(c, config):
        raise RuntimeError(config['message'])
    def provider(c, config):
        for name in config['names']:
            c.provide(name, object())
    class Pending:
        inject = ['absentService']
        def __call__(self, c):
            raise AssertionError('must stay pending')
    for name, plugin in {'contribute':contribute,'refuses':refuses,'provider':provider,'pending':Pending()}.items():
        ctx.loader.register_plugin_class('fixture:'+name,plugin)
    def rows(name, value):
        seed(tmp_path,name,yaml.safe_dump(value))
    for name in ('alpha','beta'):
        rows(name,[{'id':'contribute','name':'fixture:contribute','config':{'label':name}}])
    rows('broken',[{'id':'first','name':'fixture:refuses','config':{'message':'first-refuses'}}, {'id':'second','name':'fixture:refuses','config':{'message':'second-refuses'}}])
    rows('nested',[{'id':'outer','name':'cordis:group','config':[{'id':'inner-first','name':'fixture:refuses','config':{'message':'inner-first'}},{'id':'inner-second','name':'fixture:refuses','config':{'message':'inner-second'}}]}])
    rows('pending',[{'id':'pending','name':'fixture:pending'}])
    rows('leaky',[{'id':'provider','name':'fixture:provider','config':{'names':['aaaLeaked','zzzLeaked']}}])
    rows('isolated',[{'id':'provider','name':'fixture:provider','isolate':{'privateSvc':True},'config':{'names':['privateSvc']}}])
    await ctx.plugin(AgentPresets,{'default':'alpha','roots':[{'path':str(tmp_path),'trust':'system'}],'includeUserRoot':False,'includeShippedRoot':False})
    handles=[]
    async def agent(name, preset='alpha'):
        handle=await ctx.agents.create(session_id=name,setup=None if preset is False else lambda c: ctx.agentPresets.mount(c,preset))
        handles.append(handle)
        return handle
    def names(handle=None):
        return [t.name for t in ctx.tools.list_tools(handle.agent if handle else None)]
    def mounts():
        return [m for m in live_preset_mounts() if m.fiber.ctx.root is ctx]
    h=SimpleNamespace(ctx=ctx,root=tmp_path,agent=agent,names=names,mounts=mounts,rows=rows,handles=handles)
    try:
        yield h
    finally:
        for handle in handles:
            await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('line',[118,131,145,215,240,247,255,264,269,279,288,305,315,335,352,474,491,518,539,552,566,597,608,618,742,755,770])
async def test_mount_official_assertions(harness, monkeypatch, line):
    h=harness;ctx=h.ctx;p=ctx.agentPresets
    if line==118:
        a=await h.agent('a');b=await h.agent('b','beta')
        first=await ctx.systemPrompt.assemble({'agent':a.agent,'scope':scope_of(a.ctx)})
        second=await ctx.systemPrompt.assemble({'agent':b.agent,'scope':scope_of(b.ctx)})
        assert 'preset:alpha' in [s['name'] for s in first['sections']]
        assert 'preset:beta' not in [s['name'] for s in first['sections']]
        assert 'preset:beta' in [s['name'] for s in second['sections']]
        assert [t['name'] for t in first['tools']]==['alpha']
    elif line==131:
        assert h.names(await h.agent('default',None))==['alpha']
    elif line==145:
        gone=await h.agent('gone');survivor=await h.agent('survivor','beta')
        await gone.dispose()
        assert ctx.agents.get('gone') is None and h.names(survivor)==['beta'] and h.names()==[]
    elif line==215:
        parent=await h.agent('bare',False);child=await h.agent('child',False)
        assert p.compose_from(child.ctx,parent.ctx) is None
        assert p.composed_preset(parent.ctx) is None and h.names(child)==[]
    elif line in (240,247,255,264,269):
        preset={240:'broken',247:'broken',255:'nested',264:'pending',269:'leaky'}[line]
        pattern={240:'failed to mount',247:'first-refuses.*second-refuses',255:'outer.*inner-first.*inner-second',264:'waiting for absentService',269:'process-global service.*aaaLeaked, zzzLeaked'}[line]
        with pytest.raises(PresetMountError,match='(?s)'+pattern): await h.agent('failed',preset)
        assert ctx.agents.get('failed') is None and ctx.sessions.get('failed') is None
        assert h.names()==[] and h.mounts()==[]
        assert not any(getattr(x,'name',None) in ('aaaLeaked','zzzLeaked') for x in ctx.reflect.store.values())
    elif line in (279,288,305):
        a=await h.agent('private','isolated');value=p.service_for(a.agent,'privateSvc')
        assert value is not None and ctx.get('privateSvc',None) is None
        if line==288:
            b=await h.agent('shared','isolated');assert p.service_for(b.agent,'privateSvc') is value
        if line==305:
            b=await h.agent('other');assert p.service_for(b.agent,'privateSvc') is None
    elif line==315:
        loner=create_scope(ctx,ScopeKey('loner'));orphan=create_scope(ctx,ScopeKey('orphan'))
        bind_scope_parent(scope_of(orphan.ctx),ScopeKey('never-mounted'))
        for c in (ctx,loner.ctx,orphan.ctx): assert p.service_for(SimpleNamespace(ctx=c),'privateSvc') is None
    elif line==335:
        with pytest.raises(ValueError,match='not found.*available:.*alpha'): await p.resolve('unknown')
    elif line==352:
        assert p.defaultId=='alpha'
    elif line==474:
        a=await h.agent('gone');mount=h.mounts()[0];await a.dispose()
        assert leaked_services(ctx,mount.fiber)==[]
    elif line==491:
        a=await h.agent('selected');seen=[]
        ctx.on('agent-preset/selected',lambda sid,preset:seen.append((sid,preset)))
        a.session.append('agent-preset/selected',{'agentPreset':'beta'})
        assert seen==[('selected','beta')]
    elif line==518:
        a=await h.agent('swap');await p.standing_key_for('beta');seen=[];warnings=[]
        stop=ctx.on('tools/change',lambda:seen.append(p.composed_preset(a.ctx)))
        await p.recompose(a.ctx,'beta');assert seen==['beta'];stop()
        monkeypatch.setattr(type(ctx.logger),'warn',lambda self,message,*args:warnings.append(str(message)))
        def fail(): raise RuntimeError('listener failed')
        stop=ctx.on('tools/change',fail)
        assert (await p.recompose(a.ctx,'alpha')).id=='alpha';stop()
        assert h.names(a)==['alpha'] and len(warnings)==1 and 'tools/change listener failed' in warnings[0]
    elif line in (539,552,608,618):
        a=await h.agent('swap',False if line==608 else 'alpha')
        if line==618: (h.root/'alpha'/'agent.cordis.yml').unlink()
        with pytest.raises((ValueError,PresetMountError)): await p.recompose(a.ctx,'unknown' if line==539 else 'broken')
        assert h.names(a)==([] if line==608 else ['alpha'])
    elif line==566:
        warnings=[];monkeypatch.setattr(type(ctx.logger),'warn',lambda self,message,*args:warnings.append(str(message)))
        await h.agent('unjoined',False)
        assert len(warnings)==1 and 'unjoined' in warnings[0] and 'without joining' in warnings[0]
        warnings.clear();await h.agent('joined');assert warnings==[]
    elif line==597:
        a=await h.agent('bare',False);await p.recompose(a.ctx,'beta');assert h.names(a)==['beta']
    elif line==742:
        key=await p.standing_key_for('alpha')
        assert key['agentPreset']=='alpha' and len(h.mounts())==1
        assert ctx.agents.list()==[] and await p.standing_key_for('alpha') is key
    elif line in (755,770):
        preset=await p.resolve('alpha')
        if line==770: old=await p._ensure_standing(preset)
        (h.root/'alpha'/'agent.cordis.yml').unlink()
        if line==755:
            with pytest.raises(PresetMountError): await p._ensure_standing(preset)
            assert h.mounts()==[]
        else:
            assert await p._ensure_standing(preset) is old and len(h.mounts())==1


@pytest.mark.asyncio
@pytest.mark.parametrize('line',[366,377,384])
async def test_broken_discovery_precedes_mount(harness,line):
    h=harness;body='rows: not-a-list\n' if line==377 else '- id: x\n  name: [unclosed\n'
    seed(h.root,'damaged',body)
    preset=await h.ctx.agentPresets.resolve('damaged')
    assert preset.broken and ('top-level list' if line==377 else 'not valid YAML') in preset.broken
    if line!=384:
        with pytest.raises(PresetMountError,match='top-level list' if line==377 else 'not valid YAML'):
            if line==377: await h.ctx.agentPresets.standing_key_for('damaged')
            else: await h.agent('damaged','damaged')
        assert h.mounts()==[] and h.ctx.agents.get('damaged') is None


@pytest.mark.asyncio
@pytest.mark.parametrize('line',[393,405,582])
async def test_roster_configuration_guards(tmp_path,monkeypatch,line):
    ctx=Context()
    if line!=405: ctx.baseUrl=str(tmp_path)
    await ctx.plugin(Loader)
    config={'default':'alpha','roots':[],'includeUserRoot':False,'includeShippedRoot':False}
    try:
        if line==405:
            with pytest.raises(Exception,match='needs `ctx.baseUrl`'): await ctx.plugin(AgentPresets,config)
        else:
            await ctx.plugin(AgentPresets,config)
            if line==393:
                with pytest.raises(ValueError,match='available: none'): await ctx.agentPresets.resolve()
            else:
                warnings=[];monkeypatch.setattr(type(ctx.logger),'warn',lambda self,message,*args:warnings.append(str(message)))
                await ctx.plugin(SessionPlugin);await ctx.plugin(AgentPlugin);await ctx.plugin(AgentLoopPlugin)
                handle=await ctx.agents.create('no-roster');assert warnings==[];await handle.dispose()
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_absolute_plugin_import_92(harness):
    h=harness;plugin=h.root/'absolute.py'
    plugin.write_text("def default(ctx, config):\n    ctx.get('tools').register_tool(name='absolute', description='', parameters={}, handler=lambda args: 'ok')\n",encoding='utf-8')
    h.rows('absolute',[{'id':'absolute','name':str(plugin)}])
    assert h.names(await h.agent('absolute','absolute'))==['absolute']


@pytest.mark.asyncio
async def test_roster_precedence_342(tmp_path):
    roots=[tmp_path/'system',tmp_path/'user']
    for root in roots: seed(root,'alpha','[]\n')
    seed(roots[1],'beta','[]\n');(roots[1]/'ghost').mkdir()
    ctx=Context();ctx.baseUrl=str(tmp_path);await ctx.plugin(Loader)
    try:
        await ctx.plugin(AgentPresets,{'default':'alpha','roots':[{'path':str(root),'trust':trust} for root,trust in zip(roots,['system','user'])],'includeUserRoot':False,'includeShippedRoot':False})
        rows=await ctx.agentPresets.list();assert sorted(p.id for p in rows)==['alpha','beta','ghost']
        assert next(p for p in rows if p.id=='alpha').trust=='system'
        assert 'is missing' in next(p for p in rows if p.id=='ghost').broken
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_self_disposing_row_preserves_input_420(harness):
    h=harness;gate=asyncio.Event();done=asyncio.Event()
    def self_dispose(c):
        async def later():
            await gate.wait();await c.fiber.dispose();done.set()
        asyncio.create_task(later())
    h.ctx.loader.register_plugin_class('fixture:self-dispose',self_dispose)
    h.rows('self-disposing',[{'id':'kept','name':'fixture:contribute','config':{'label':'kept'}},{'id':'goes-away','name':'fixture:self-dispose'}])
    path=h.root/'self-disposing'/'agent.cordis.yml';before=path.read_bytes()
    a=await h.agent('self','self-disposing');gate.set();await asyncio.wait_for(done.wait(),3)
    await asyncio.sleep(0)
    assert path.read_bytes()==before and h.names(a)==['kept']


@pytest.mark.asyncio
@pytest.mark.parametrize('line',[41,79,100])
async def test_invariant_official_assertions(harness,monkeypatch,line):
    h=harness;ctx=h.ctx
    await ctx.plugin(InvariantRegistry);await ctx.plugin(AgentPresetsInvariantPlugin)
    if line==41:
        first=await h.agent('first');mount=h.mounts()[0];await first.dispose()
        assert h.mounts()==[mount]
        await h.agent('second');assert h.mounts()==[mount]
        await ctx.fiber.dispose();assert h.mounts()==[]
    elif line==79:
        assert (await h.agent('private','isolated')).id=='private'
    else:
        # Reinstall the roster using only the derived home root, not configured roots.
        await ctx.agentPresets.ctx.fiber.dispose()
        monkeypatch.setenv('DSH_HOME',str(h.root/'home'))
        await ctx.plugin(AgentPresets,{'default':'alpha','roots':[],'includeUserRoot':True,'includeShippedRoot':False})
        bare=await h.agent('derived',False)
        with pytest.raises(InvariantError,match='without joining any agent preset'):
            await ctx.systemPrompt.assemble({'agent':bare.agent,'scope':scope_of(bare.ctx)})

@pytest.mark.asyncio
@pytest.mark.parametrize('line',[109,137,171,181,192,206,227,235,327,503,658,682,697])
async def test_mount_scope_matrix(harness,line):
    from dsh.presets import mount_preset
    h=harness;ctx=h.ctx;p=ctx.agentPresets
    if line in (227,235,327,658):
        with pytest.raises(RuntimeError,match='unscoped context'):
            if line==227:
                a=await h.agent('parent');p.compose_from(ctx,a.ctx)
            elif line==235: await p.mount(ctx,'alpha')
            elif line==327: await mount_preset(ctx,await p.resolve('alpha'))
            else: await p.recompose(ctx,'beta')
        return
    first=await h.agent('first')
    if line in (109,137,503):
        second=await h.agent('second','beta' if line==109 else 'alpha')
        if line==503: await p.recompose(second.ctx,'beta')
        assert h.names(first)==['alpha']
        assert h.names(second)==(['beta'] if line in (109,503) else ['alpha'])
        assert h.names()==[]
    elif line in (171,181,192,206):
        before=list(h.mounts())
        child=await ctx.agents.create('child',setup=lambda c:p.compose_from(c,first.ctx));h.handles.append(child)
        if line==192: await first.dispose()
        assert h.names(child)==['alpha'] and h.mounts()==before
        assert p.composed_preset(first.ctx)==p.composed_preset(child.ctx)=='alpha'
        prompt=await ctx.systemPrompt.assemble({'agent':child.agent,'scope':scope_of(child.ctx)})
        assert 'preset:alpha' in [s['name'] for s in prompt['sections']]
    else:
        h.rows('alpha',[{'id':'contribute','name':'fixture:contribute','config':{'label':'afterwards'}}])
        later=await asyncio.gather(h.agent('later'),h.agent('racer')) if line==697 else [await h.agent('later')]
        assert h.names(first)==['alpha']
        assert all(h.names(a)==['afterwards'] for a in later)
        assert len(h.mounts())==2


@pytest.mark.asyncio
@pytest.mark.parametrize('line',[67,88,112,122])
async def test_invariant_guard_matrix(harness,line):
    h=harness;ctx=h.ctx;p=ctx.agentPresets
    await ctx.plugin(InvariantRegistry);await ctx.plugin(AgentPresetsInvariantPlugin)
    if line==67:
        await h.agent('joined')
        with pytest.raises(InvariantError,match='published process-global service.*lateService'):
            h.mounts()[0].fiber.ctx.provide('lateService',object())
    elif line==88:
        bare=await h.agent('bare',False)
        with pytest.raises(InvariantError,match='without joining any agent preset'):
            await ctx.systemPrompt.assemble({'agent':bare.agent,'scope':scope_of(bare.ctx)})
    elif line==112:
        await p.ctx.fiber.dispose()
        await ctx.plugin(AgentPresets,{'default':'alpha','roots':[],'includeUserRoot':False,'includeShippedRoot':False})
        bare=await h.agent('bare',False)
        await ctx.systemPrompt.assemble({'agent':bare.agent,'scope':scope_of(bare.ctx)})
    else:
        joined=await h.agent('joined')
        await ctx.systemPrompt.assemble({'agent':joined.agent,'scope':scope_of(joined.ctx)})
        await ctx.systemPrompt.assemble({})
        await ctx.systemPrompt.assemble({'scope':await p.standing_key_for('alpha')})
