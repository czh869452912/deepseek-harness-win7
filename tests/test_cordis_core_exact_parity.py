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
    # reflect.ts `ReflectService.get` reads the store without the proxy
    # waterfall, so `ctx.get(...)` is not intercepted.
    assert get_log == []

    captured = {}

    class ReaderPlugin(Plugin):
        name = 'internal-get-reader'
        inject = ['db']

        def apply(self, c: Context) -> None:
            captured['value'] = c.db.value

    ctx.plugin(ReaderPlugin)
    assert captured['value'] == 42
    assert [entry[0] for entry in get_log] == ['db']

    # Test short-circuiting in internal/get
    def on_get_override(target_ctx, prop, error, next_fn):
        if prop == 'custom_virtual':
            return 'intercepted_virtual_value'
        return next_fn()

    ctx.on('internal/get', on_get_override, prepend=True)

    overridden = {}

    class VirtualReaderPlugin(Plugin):
        name = 'internal-get-virtual-reader'

        def apply(self, c: Context) -> None:
            overridden['virtual'] = c.custom_virtual

    ctx.plugin(VirtualReaderPlugin)
    assert overridden['virtual'] == 'intercepted_virtual_value'


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

        await entry.init()
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
        hmr = HmrService(ctx, config={'debounce': 10, 'root': []})
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
        new_fiber = reloads[0][plugin_cls]["runtime"].fibers[0]
        assert new_fiber.plugin.version == 2
        assert fiber.plugin.version == 2
        hmr.teardown()


@pytest.mark.asyncio
async def test_hmr_dynamic_module_reload_failure_triggers_rollback():
    """R4 test: Module reload failure triggers deep rollback restoring previous plugin and fiber state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mod_file = os.path.join(tmpdir, 'failing_plugin.py')
        with open(mod_file, 'w', encoding='utf-8') as f:
            f.write(
                'from dsh.cordis.plugin import Plugin\n'
                'class FailingSamplePlugin(Plugin):\n'
                '    id = \'failing-sample\'\n'
                '    def apply(self, ctx):\n'
                '        self.version = 1\n'
            )

        ctx = Context()
        hmr = HmrService(ctx, config={'debounce': 10, 'root': []})
        ctx.set_service('hmr', hmr)

        import importlib.util
        spec = importlib.util.spec_from_file_location('failing_plugin', mod_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        plugin_cls = getattr(mod, 'FailingSamplePlugin')

        fiber = ctx.plugin(plugin_cls)
        assert fiber.plugin.version == 1

        changes = []
        ctx.on('hmr/change', lambda fn: changes.append(fn))
        hmr.register_module(mod_file, plugin_cls)

        await asyncio.sleep(0.05)
        # Update file with code that raises on apply
        new_mtime = os.path.getmtime(mod_file) + 2.0
        with open(mod_file, 'w', encoding='utf-8') as f:
            f.write(
                'from dsh.cordis.plugin import Plugin\n'
                'class FailingSamplePlugin(Plugin):\n'
                '    id = \'failing-sample\'\n'
                '    def apply(self, ctx):\n'
                '        raise RuntimeError("boom on reload")\n'
            )
        os.utime(mod_file, (new_mtime, new_mtime))

        for _ in range(30):
            await asyncio.sleep(0.05)
            if changes:
                break

        # Give rollback time to settle
        await asyncio.sleep(0.1)

        assert len(changes) >= 1
        # Previous plugin was restored on rollback:
        # X5 discriminating assertions: verify old_cls remains registered in registry and its active fiber is restored
        assert ctx.registry.has(plugin_cls)
        restored_runtime = ctx.registry.get(plugin_cls)
        assert restored_runtime is not None
        assert len(restored_runtime.fibers) >= 1
        assert restored_runtime.fibers[0].plugin.version == 1
        assert fiber.plugin.version == 1
        hmr.teardown()


@pytest.mark.asyncio
async def test_hmr_multi_file_reload_failure_triggers_rollback_all():
    """X2 test: Multi-file reload failure rolls back all affected modules and restores all previous fibers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_a = os.path.join(tmpdir, 'plugin_a.py')
        file_b = os.path.join(tmpdir, 'plugin_b.py')

        with open(file_a, 'w', encoding='utf-8') as f:
            f.write(
                'from dsh.cordis.plugin import Plugin\n'
                'class MultiSamplePluginA(Plugin):\n'
                '    id = \'multi-sample-a\'\n'
                '    def apply(self, ctx):\n'
                '        self.version = 1\n'
            )

        with open(file_b, 'w', encoding='utf-8') as f:
            f.write(
                'from dsh.cordis.plugin import Plugin\n'
                'class MultiSamplePluginB(Plugin):\n'
                '    id = \'multi-sample-b\'\n'
                '    def apply(self, ctx):\n'
                '        self.version = 1\n'
            )

        ctx = Context()
        # [ADAPT] config uses root: [] to avoid scanning the active repository root in unit tests.
        hmr = HmrService(ctx, config={'debounce': 10, 'root': []})
        ctx.set_service('hmr', hmr)

        import importlib.util
        spec_a = importlib.util.spec_from_file_location('plugin_a', file_a)
        mod_a = importlib.util.module_from_spec(spec_a)
        spec_a.loader.exec_module(mod_a)
        cls_a = getattr(mod_a, 'MultiSamplePluginA')

        spec_b = importlib.util.spec_from_file_location('plugin_b', file_b)
        mod_b = importlib.util.module_from_spec(spec_b)
        spec_b.loader.exec_module(mod_b)
        cls_b = getattr(mod_b, 'MultiSamplePluginB')

        fiber_a = ctx.plugin(cls_a)
        fiber_b = ctx.plugin(cls_b)
        assert fiber_a.plugin.version == 1
        assert fiber_b.plugin.version == 1

        changes = []
        ctx.on('hmr/change', lambda fn: changes.append(fn))
        hmr.register_module(file_a, cls_a)
        hmr.register_module(file_b, cls_b)

        # Set dependency: file_b depends on file_a so modifying file_a triggers reload of both
        hmr.graph.add_dependency(file_b, file_a)

        await asyncio.sleep(0.05)
        mtime_a = os.path.getmtime(file_a) + 2.0
        with open(file_a, 'w', encoding='utf-8') as f:
            f.write(
                'from dsh.cordis.plugin import Plugin\n'
                'class MultiSamplePluginA(Plugin):\n'
                '    id = \'multi-sample-a\'\n'
                '    def apply(self, ctx):\n'
                '        self.version = 2\n'
            )
        os.utime(file_a, (mtime_a, mtime_a))

        mtime_b = os.path.getmtime(file_b) + 2.0
        with open(file_b, 'w', encoding='utf-8') as f:
            f.write(
                'from dsh.cordis.plugin import Plugin\n'
                'class MultiSamplePluginB(Plugin):\n'
                '    id = \'multi-sample-b\'\n'
                '    def apply(self, ctx):\n'
                '        raise RuntimeError("boom in plugin_b reload")\n'
            )
        os.utime(file_b, (mtime_b, mtime_b))

        for _ in range(30):
            await asyncio.sleep(0.05)
            if changes:
                break

        await asyncio.sleep(0.15)
        assert len(changes) >= 1

        # X2 verification: BOTH plugin A and plugin B are restored to version 1 in ctx.registry
        assert ctx.registry.has(cls_a)
        runtime_a = ctx.registry.get(cls_a)
        assert runtime_a is not None and len(runtime_a.fibers) >= 1
        assert runtime_a.fibers[0].plugin.version == 1

        assert ctx.registry.has(cls_b)
        runtime_b = ctx.registry.get(cls_b)
        assert runtime_b is not None and len(runtime_b.fibers) >= 1
        assert runtime_b.fibers[0].plugin.version == 1

        hmr.teardown()

