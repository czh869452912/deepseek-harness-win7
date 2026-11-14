import ast
import gc
from pathlib import Path
import shutil
import sys
import types
import weakref

import pytest

from scripts.rc022_hmr_graph_probe import observe


@pytest.mark.asyncio
async def test_actual_static_dynamic_and_runtime_import_graph(tmp_path):
    assert await observe(tmp_path/'files') == [
        dict(mode='static-dynamic', before=[['entry', 'dep']], after=[['entry', 'dep']], after_disk=[['entry', 'dep']], value=2),
        dict(mode='runtime-import', before=[['entry', 'dep']], after=[['entry', 'dep'], ['entry', 'late']],
             after_disk=[['entry', 'dep'], ['entry', 'late']], value=2),
    ]


@pytest.mark.asyncio
async def test_descriptor_import_records_real_host_file_and_relative_dependency(tmp_path):
    from dsh.cordis import Context
    from dsh.cordis.loader import Loader
    from dsh.cordis.hmr_modules import PythonModules
    root = Path(__file__).resolve().parents[1]
    directory = tmp_path/'plugin'
    shutil.copytree(str(root/'examples/python-echo'), str(directory), ignore=shutil.ignore_patterns('__pycache__'))
    ctx = Context()
    loader = Loader(ctx)
    cache = PythonModules(ctx)
    namespace = None
    try:
        plugin = loader.import_plugin(str(directory/'package.json'))
        namespace = plugin.__module__.split('.')[0]
        entry = directory/'python/echo/plugin.py'
        helper = directory/'python/echo/formatting.py'
        assert entry.as_uri() in loader.internal.loadCache
        assert (directory/'package.json').as_uri() not in loader.internal.loadCache
        assert helper.as_uri() in cache.get_linked(entry.as_uri())
    finally:
        if namespace is not None:
            for name in list(sys.modules):
                if name == namespace or name.startswith(namespace+'.'):
                    sys.modules.pop(name, None)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_traced_graph_does_not_read_changed_source(tmp_path, monkeypatch):
    from dsh.cordis import Context
    from dsh.cordis.hmr_modules import PythonModules, load_python_file
    path = tmp_path/'plugin.py'
    path.write_text('import json\n', encoding='utf-8')
    module = load_python_file(str(path), '_rc022_graph_file')
    path.write_text('syntax = (\n', encoding='utf-8')
    ctx = Context()
    cache = PythonModules(ctx)
    try:
        expected = list(module._dsh_hmr_links)
        def forbidden(*args, **kwargs):
            raise AssertionError('loaded trace must not parse source again')
        monkeypatch.setattr(ast, 'parse', forbidden)
        assert cache.get_linked(path.as_uri()) == expected
    finally:
        sys.modules.pop(module.__name__, None)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unloaded_fallback_snapshots_do_not_keep_old_modules_alive(tmp_path):
    from dsh.cordis import Context
    from dsh.cordis.hmr_modules import PythonModules
    module = types.ModuleType('_rc022_graph_retired')
    module.__file__ = str(tmp_path/'missing.py')
    ctx = Context()
    cache = PythonModules(ctx)
    try:
        assert cache._links(module) == []
        reference = weakref.ref(module)
        del module
        gc.collect()
        assert reference() is None
        assert len(cache._snapshots) == 0
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_preexisting_module_graph_keeps_snapshot_and_ignores_opaque_values(tmp_path):
    from dsh.cordis import Context
    from dsh.cordis.hmr_modules import PythonModules
    import json
    path = tmp_path/'legacy.py'
    path.write_text('import json\n', encoding='utf-8')
    module = types.ModuleType('_rc022_graph_old')
    module.__file__, module.__package__ = str(path), ''
    class Opaque:
        def __getattr__(self, key): raise AssertionError(key)
    module.opaque = Opaque()
    sys.modules[module.__name__] = module
    ctx = Context()
    cache = PythonModules(ctx)
    try:
        first = cache.get_linked(path.as_uri())
        assert json.__file__ is not None and len(first) == 1
        path.write_text('import pathlib\n', encoding='utf-8')
        assert cache.get_linked(path.as_uri()) == first
    finally:
        sys.modules.pop(module.__name__, None)
        await ctx.fiber.dispose()
