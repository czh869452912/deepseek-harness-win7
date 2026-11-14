import importlib
import os
from pathlib import Path
import py_compile
import sys
import types

import pytest

from dsh.cordis import Context
from dsh.cordis.hmr_modules import PythonModules, load_python_file
from dsh.cordis.loader import Loader
from scripts.rc022_hmr_cache_probe import observe


@pytest.mark.asyncio
async def test_evaluated_modules_and_failed_import_restore_previous_cache(tmp_path):
    assert await observe(tmp_path/'files') == [
        dict(case='success', retained=True, retained_value=1, failed=False, value=2, replaced=True, restored=True, restored_value=1),
        dict(case='failure', retained=True, retained_value=1, failed=True, value=None, replaced=None, restored=True, restored_value=1),
        dict(case='unrelated', retained=True, retained_value=1, failed=False, value=1, replaced=False, restored=True, restored_value=1),
    ]


@pytest.mark.asyncio
async def test_eviction_removes_module_aliases_parent_attributes_and_loader_aliases(tmp_path):
    ctx = Context()
    loader = Loader(ctx)
    cache = PythonModules(ctx)
    path = tmp_path/'plugin.py'
    path.write_text('class Plugin: pass\n', encoding='utf-8')
    module = load_python_file(str(path), '_rc022_cache_parent.child')
    parent = types.ModuleType('_rc022_cache_parent')
    parent.child = module
    sys.modules[parent.__name__] = parent
    sys.modules['_rc022_cache_alias'] = module
    loader.internal.loadCache[path.as_uri()] = module
    loader.registry_map['owned'] = module.Plugin
    loader.registry_map['unrelated'] = object()
    loader._module_aliases[module.__name__] = {'owned', 'unrelated'}
    try:
        rollback = cache.evict([path.as_uri()])
        assert path.as_uri() not in loader.internal.loadCache
        assert module.__name__ not in sys.modules and '_rc022_cache_alias' not in sys.modules
        assert not hasattr(parent, 'child')
        assert 'owned' not in loader.registry_map and 'unrelated' in loader.registry_map
        parent.child = object()
        rollback()
        assert parent.child is module
        assert sys.modules[module.__name__] is sys.modules['_rc022_cache_alias'] is module
        assert loader.internal.loadCache[path.as_uri()] is module
        assert loader.registry_map['owned'] is module.Plugin
    finally:
        for name in [parent.__name__, module.__name__, '_rc022_cache_alias']:
            sys.modules.pop(name, None)
        finder = cache._finder
        await ctx.fiber.dispose()
        assert finder not in sys.meta_path


@pytest.mark.asyncio
async def test_same_size_same_tick_source_reloads_without_deleting_bytecode(tmp_path, monkeypatch):
    ctx = Context()
    cache = PythonModules(ctx)
    path = tmp_path/'_rc022_cached_dependency.py'
    path.write_text('value = 1\n', encoding='utf-8')
    bytecode = py_compile.compile(str(path), doraise=True)
    original_time = path.stat().st_mtime_ns
    original_bytes = Path(bytecode).read_bytes()
    monkeypatch.syspath_prepend(str(tmp_path))
    name = path.stem
    try:
        first = importlib.import_module(name)
        path.write_text('value = 2\n', encoding='utf-8')
        os.utime(str(path), ns=(original_time, original_time))
        rollback = cache.evict([path.as_uri()])
        second = importlib.import_module(name)
        assert first.value == 1 and second.value == 2
        assert Path(bytecode).read_bytes() == original_bytes
        rollback()
        assert importlib.import_module(name) is first
    finally:
        sys.modules.pop(name, None)
        await ctx.fiber.dispose()


def test_failed_source_does_not_publish_a_partial_module(tmp_path):
    path = tmp_path/'failed.py'
    path.write_text('value = 1\nraise RuntimeError("execution failed")\n', encoding='utf-8')
    with pytest.raises(RuntimeError, match='execution failed'):
        load_python_file(str(path), '_rc022_partial_module')
    assert '_rc022_partial_module' not in sys.modules
