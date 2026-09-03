import asyncio
import os
import sys
import tempfile
import time
import pytest

from dsh.cordis.context import Context
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.loader import Loader, Entry
from dsh.cordis.hmr import HmrService


@pytest.mark.asyncio
async def test_reflect_internal_get_waterfall_signature_1to1():
    ctx = Context()

    class DatabaseService(Service):
        name = 'db'
        def __init__(self, ctx, config=None):
            super().__init__(ctx, 'db')
            self.value = 42

    ctx.plugin(DatabaseService)
    assert ctx.get('db').value == 42

    get_log = []

    def on_get(target_ctx, prop, error, next_fn):
        get_log.append((prop, error is not None))
        val = next_fn()
        return val

    ctx.on('internal/get', on_get)

    res = ctx.get('db')
    assert res.value == 42
    assert len(get_log) == 1
    assert get_log[0][0] == 'db'

    # Test short-circuiting in internal/get
    def on_get_override(target_ctx, prop, error, next_fn):
        if prop == 'custom_virtual':
            return 'intercepted_virtual_value'
        return next_fn()

    ctx.on('internal/get', on_get_override, prepend=True)
    assert ctx.get('custom_virtual') == 'intercepted_virtual_value'


@pytest.mark.asyncio
async def test_reflect_internal_set_waterfall_signature_1to1():
    ctx = Context()

    class ConfigService(Service):
        name = 'cfg'
        def __init__(self, ctx, config=None):
            super().__init__(ctx, 'cfg')
            self.data = 'initial'

    ConfigService(ctx)

    set_log = []

    def on_set(target_ctx, prop, value, error, next_fn):
        set_log.append((prop, value))
        return next_fn()

    ctx.on('internal/set', on_set)

    ctx.set('cfg', 'updated')
    assert len(set_log) == 1
    assert set_log[0] == ('cfg', 'updated')
    assert ctx.get('cfg') == 'updated'


@pytest.mark.asyncio
async def test_loader_internal_plugin_7_cases_and_tree_write():
    with tempfile.TemporaryDirectory() as tmpdir:
        patch_file = os.path.join(tmpdir, 'cordis.patch.yml')
        ctx = Context()

        class DummyPlugin(Plugin):
            id = 'dummy'
            def __init__(self, config=None):
                super().__init__(config)

        loader = Loader(ctx)
        loader.filepath = patch_file
        loader.register_plugin_class('dummy', DummyPlugin)

        entry_id = loader.create({'name': 'dummy', 'id': 'dummy-1', 'config': {'key': 'val'}})
        entry = loader.resolve(entry_id)
        assert entry is not None
        assert entry.disabled is False

        entry.init()
        assert entry.fiber is not None

        # Disposing fiber manually should trigger Case 7 and mark entry disabled and call write()
        await entry.fiber.dispose()
        assert entry.disabled is True
        assert entry.options.get('disabled') is True

        # Verify tree.write wrote out YAML to patch_file
        assert os.path.exists(patch_file)
        with open(patch_file, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'dummy-1' in content


@pytest.mark.asyncio
async def test_hmr_dynamic_module_reload_and_fiber_restart():
    with tempfile.TemporaryDirectory() as tmpdir:
        mod_file = os.path.join(tmpdir, 'dynamic_plugin.py')
        with open(mod_file, 'w', encoding='utf-8') as f:
            f.write(
                'from dsh.cordis.plugin import Plugin\n'
                'class DynamicSamplePlugin(Plugin):\n'
                '    id = \'dynamic-sample\'\n'
                '    def apply(self, ctx):\n'
                '        self.version = 1\n'
            )

        ctx = Context()
        hmr = HmrService(ctx, config={'debounce': 10})
        ctx.set_service('hmr', hmr)

        import importlib.util
        spec = importlib.util.spec_from_file_location('dynamic_plugin', mod_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        plugin_cls = getattr(mod, 'DynamicSamplePlugin')

        fiber = ctx.plugin(plugin_cls)
        assert fiber.plugin.version == 1

        changes = []
        reloads = []

        ctx.on('hmr/change', lambda fn: changes.append(fn))
        ctx.on('hmr/reload', lambda r: reloads.append(r))

        hmr.register_module(mod_file, plugin_cls)

        await asyncio.sleep(0.1)
        # Update file with future mtime
        new_mtime = os.path.getmtime(mod_file) + 2.0
        with open(mod_file, 'w', encoding='utf-8') as f:
            f.write(
                'from dsh.cordis.plugin import Plugin\n'
                'class DynamicSamplePlugin(Plugin):\n'
                '    id = \'dynamic-sample\'\n'
                '    def apply(self, ctx):\n'
                '        self.version = 2\n'
            )
        os.utime(mod_file, (new_mtime, new_mtime))

        for _ in range(30):
            await asyncio.sleep(0.05)
            if reloads:
                break

        assert len(changes) >= 1
        assert len(reloads) >= 1
        assert fiber.plugin.version == 2
        hmr.teardown()
