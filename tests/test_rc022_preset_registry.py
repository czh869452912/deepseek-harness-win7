import pytest
import yaml

from scripts.rc022_preset_registry_probe import observe
from scripts.rc022_subagent_fixture import setup
from dsh.cordis.loader import Loader
from dsh.presets.registry_current import CurrentAgentPreset, CurrentAgentPresetRegistry


@pytest.mark.asyncio
async def test_retained_generations_and_actual_delegated_model_tools(tmp_path):
    rows = await observe(tmp_path)
    assert len(rows) == 21
    assert rows[6]['parent']['tools'] == ['coding_only']
    assert rows[7]['newest']['tools'] == ['coding_v2']
    assert rows[8]['inherited']['preset'] == 'coding'
    assert rows[9]['selectionNoop']
    assert rows[13]['modelTools'] == ['coding_v2']
    assert rows[14]['modelTools'] == ['reviewing_only']
    assert rows[15]['locked']['code'] == 'agent-preset/locked'
    assert rows[18]['preservedExpression']
    assert rows[19]['declarationRemoved']
    assert rows[20]['sortedIds'] == ['中', 'á', 'a', 'A', 'z', 'Z']


@pytest.mark.asyncio
async def test_declarative_carrier_lifecycle_relative_base_and_yaml(tmp_path):
    fixture = await setup(tmp_path / 'host'); ctx = fixture.ctx
    declaring = tmp_path / 'declaring'; declaring.mkdir()
    (declaring / 'plugin.py').write_text(
        'from dsh.cordis.plugin import Plugin\n'
        'class Relative(Plugin):\n'
        '    def apply(self, ctx):\n'
        '        ctx.emit("fixture/loaded", self.config["value"])\n'
        'default = Relative\n', encoding='utf-8')
    loaded = []
    ctx.on('fixture/loaded', loaded.append)
    try:
        await ctx.plugin(Loader)
        await ctx.plugin(CurrentAgentPresetRegistry, dict(default='relative'))
        child = ctx.extend(dict(baseUrl=declaring.as_uri() + '/'))
        rows = [dict(id='relative-module', name='./plugin.py', config=dict(value='模块'))]
        carrier = await child.plugin(CurrentAgentPreset, dict(id='relative', name='相对路径', plugins=rows))
        assert await ctx.agentPresets.resolve() == dict(id='relative')
        assert loaded == ['模块']
        document = await ctx.agentPresets.readDocument('relative')
        assert yaml.safe_load(document['content']) == rows
        lease = await ctx.agentPresets.acquireScope()
        await carrier.dispose()
        assert await ctx.agentPresets.list() == []
        assert [item['id'] for item in ctx.agentPresets.inspectCompositions()] == ['relative']
        await lease.dispose()
        assert ctx.agentPresets.inspectCompositions() == []
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_pending_dependencies_reaudit_and_unisolated_services_rejected(tmp_path):
    fixture = await setup(tmp_path / 'host'); ctx = fixture.ctx
    def waiting(child, config):
        pass
    waiting.inject = ['fixtureDependency']
    def leaking(child, config):
        child.set_service('fixtureLeak', object())
    try:
        await ctx.plugin(Loader)
        ctx.loader.builtins.update(waiting=waiting, leaking=leaking)
        await ctx.plugin(CurrentAgentPresetRegistry, dict(default='pending'))
        presets = ctx.agentPresets
        await presets.register(dict(id='pending', plugins=[dict(id='wait', name='cordis:waiting')]))
        assert 'waiting for fixtureDependency' in (await presets.resolve())['broken']
        ctx.set_service('fixtureDependency', object())
        await ctx.loader.wait()
        assert await presets.resolve() == dict(id='pending')
        await presets.register(dict(id='leak', plugins=[dict(id='leak', name='cordis:leaking')]))
        assert (await presets.resolve('leak'))['broken'] == 'Preset services require isolate realms: fixtureLeak'
        assert ctx.get('fixtureLeak') is None
    finally:
        await ctx.fiber.dispose()
