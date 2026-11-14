"""Reversible Python module eviction and source loading for hot replacement."""
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import types


def module_url(module):
    filename = getattr(module, '__file__', None)
    return Path(os.path.realpath(filename)).as_uri() if isinstance(filename, str) else None


class FreshSourceLoader(importlib.machinery.SourceFileLoader):
    def exec_module(self, module):
        # Compile the actual source: same-size edits within one filesystem tick
        # must not read a still-valid timestamp-based .pyc from the old version.
        source = self.get_data(self.path)
        code = compile(source, self.path, 'exec')
        module._dsh_hmr_source = source
        exec(code, module.__dict__)


def load_python_file(filename, module_name):
    filename = os.path.abspath(filename)
    previous = sys.modules.get(module_name)
    if isinstance(previous, types.ModuleType) and module_url(previous) == Path(os.path.realpath(filename)).as_uri():
        return previous
    loader = FreshSourceLoader(module_name, filename)
    spec = importlib.util.spec_from_file_location(module_name, filename, loader=loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        loader.exec_module(module)
    except BaseException:
        if sys.modules.get(module_name) is module:
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous
        raise
    return module


class _FreshFinder(importlib.abc.MetaPathFinder):
    def __init__(self, urls):
        self.urls = urls

    def find_spec(self, fullname, path=None, target=None):
        if not self.urls:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is not None and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            if Path(os.path.realpath(spec.origin)).as_uri() in self.urls:
                spec.loader = FreshSourceLoader(fullname, spec.origin)
                return spec
        return None


class PythonModules:
    def __init__(self, ctx):
        self.ctx = ctx
        self._fresh_urls = set()
        self._finder = None

    def dispose(self):
        if self._finder is not None:
            sys.meta_path[:] = [finder for finder in sys.meta_path if finder is not self._finder]
            self._finder = None
        self._fresh_urls.clear()

    def _install(self):
        if self._finder is None:
            finder = _FreshFinder(self._fresh_urls)
            self.ctx.effect(lambda: self.dispose, label='hmr.python-module-cache')
            self._finder = finder
            sys.meta_path.insert(0, finder)

    def evict(self, urls):
        """Remove evaluated modules and return an exact cache restoration effect."""
        urls = set(urls)
        self._install()
        self._fresh_urls.update(urls)
        loader = self.ctx.get('loader')
        cache = getattr(getattr(loader, 'internal', None), 'loadCache', {})
        cached = {url:cache.pop(url) for url in list(cache) if url in urls}
        modules = {name:module for name, module in list(sys.modules.items()) if module_url(module) in urls}
        parents, aliases = [], {}
        for name, module in modules.items():
            sys.modules.pop(name, None)
            parent_name, unused, child = name.rpartition('.')
            parent = sys.modules.get(parent_name) or modules.get(parent_name)
            if parent is not None and getattr(parent, child, None) is module:
                parents.append((parent, child, module))
                delattr(parent, child)
            for alias in getattr(loader, '_module_aliases', {}).get(name, ()):
                value = loader.registry_map.get(alias)
                if value is module or (getattr(value, '__module__', None) == name
                        and getattr(module, getattr(value, '__name__', ''), None) is value):
                    aliases[alias] = loader.registry_map.pop(alias)
        importlib.invalidate_caches()

        def rollback():
            cache.update(cached)
            sys.modules.update(modules)
            for parent, child, module in parents:
                setattr(parent, child, module)
            if aliases:
                loader.registry_map.update(aliases)
        return rollback
