import asyncio
import os
import sys
import types

import pytest

from scripts.rc022_hmr_roots_probe import FILES, observe


@pytest.mark.asyncio
async def test_ready_inventory_root_options_and_change_only_membership(tmp_path):
    rows = await asyncio.wait_for(observe(tmp_path/'roots'), 15)
    by_name = {row['name']:row for row in rows}
    assert all(row.get('ready', True) for row in rows)
    assert by_name['empty']['events'] == sorted(FILES)
    assert by_name['relative-base']['events'] == sorted(FILES)
    assert by_name['file']['events'] == ['top.txt']
    assert by_name['depth']['events'] == ['.hidden', 'top.tmp', 'top.txt']
    assert by_name['literal-root']['events'] == []
    assert by_name['unfollowed-root']['events'] == []
    assert by_name['linked-root']['events'] == sorted(name for name in FILES if name.startswith('sub/'))
    excluded = {'.hidden', 'node_modules/pkg.txt', 'cache/a.txt', 'data/a.txt'}
    if os.name != 'nt':
        excluded.add('sub/.secret/a.txt')
    assert by_name['defaults']['events'] == sorted(set(FILES)-excluded)
    assert by_name['membership'] == dict(name='membership', added=[], changed=['added.txt'],
                                        deleted=[], restored=[], rechanged=['added.txt'])


def test_ignore_patterns_keep_globstar_dot_case_and_native_separator_rules():
    from dsh.cordis.hmr_glob import matches
    assert matches('foo', ['foo/**'])
    assert matches('foo/bar', ['foo/**/bar'])
    assert not matches('foo/.hidden/bar', ['foo/**/bar'])
    assert matches('foo\\bar.tmp', ['*.tmp'])
    assert not matches('foo/bar.tmp', ['*.tmp'])
    assert matches('a.txt', ['[!a].txt'])
    assert not matches('b.txt', ['[!a].txt'])
    assert matches('bar/b', ['{foo,bar}/**'])
    assert not matches('file.js', ['*.JS'])
    with pytest.raises(ValueError, match='non-empty'):
        matches('any', [''])


@pytest.mark.asyncio
async def test_host_external_graph_stops_at_installed_modules(tmp_path, monkeypatch):
    from dsh.cordis.context import Context
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.hmr_modules import module_url
    from dsh.cordis.loader import Loader
    from dsh.cordis.timer import TimerService
    modules = []
    for name in ('entry.py', 'local.py', 'node_modules/pkg.py', 'behind.py'):
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('', encoding='utf-8')
        module = types.ModuleType(name)
        module.__file__ = str(path)
        module._dsh_hmr_links = []
        modules.append(module)
    urls = list(map(module_url, modules))
    modules[0]._dsh_hmr_links = urls[1:3]
    modules[1]._dsh_hmr_links = [urls[0]]
    modules[2]._dsh_hmr_links = [urls[3]]
    monkeypatch.setattr(sys, 'argv', [modules[0].__file__])
    monkeypatch.setitem(sys.modules, '__main__', modules[0])
    for index, module in enumerate(modules[1:]):
        monkeypatch.setitem(sys.modules, '_rc022_host_'+str(index), module)
    ctx = Context()
    ctx.baseUrl = tmp_path.as_uri()+'/'
    await ctx.plugin(Loader)
    await ctx.plugin(TimerService)
    try:
        await ctx.plugin(ConfigWatcherService, dict(root=[]))
        hmr = ctx.get('hmr')
        assert hmr.externals == set(urls[:2])
        assert hmr.modules.host_modules() == set(urls)
    finally:
        await ctx.fiber.dispose()


def test_external_graph_does_not_traverse_native_installed_runtime(tmp_path, monkeypatch):
    from dsh.cordis.context import Context
    from dsh.cordis.hmr_modules import PythonModules, module_url
    import dsh.cordis.context as runtime
    main = types.ModuleType('__main__')
    main.__file__ = str(tmp_path/'entry.py')
    (tmp_path/'entry.py').write_text('', encoding='utf-8')
    main._dsh_hmr_links = [module_url(runtime)]
    monkeypatch.setitem(sys.modules, '__main__', main)
    monkeypatch.setattr(sys, 'argv', [main.__file__])
    modules = PythonModules(Context())
    original = modules._links
    def links(module):
        assert module is main, 'installed SDK graph must remain opaque'
        return original(module)
    monkeypatch.setattr(modules, '_links', links)
    assert modules.external_modules() == {module_url(main)}
