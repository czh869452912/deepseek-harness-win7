"""Reversible Python module eviction and source loading for hot replacement."""
import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import ast
import asyncio
import builtins
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import types
import weakref
from collections import deque

_MODULE_URLS = weakref.WeakKeyDictionary()
_MODULE_IMPORTS = weakref.WeakKeyDictionary()


def _static_imports(module):
    """Keep compact syntax edges for an evaluated module across HMR owners.

    Resolve targets from sys.modules later: a cached syntax edge must not keep
    an old imported module alive or hide a replacement. A new ModuleSpec (as
    created by importlib.reload) invalidates the syntax snapshot.
    """
    filename=getattr(module,'__file__','')
    spec=getattr(module,'__spec__',None)
    source=getattr(module,'_dsh_hmr_source',None)
    cached=_MODULE_IMPORTS.get(module)
    if cached is not None and cached[0]==filename and cached[1]() is spec and cached[2] is source:
        return cached[3]
    if source is None and isinstance(filename,str) and filename.endswith(('.py','.pyw')):
        try:
            with open(filename,'rb') as stream:source=stream.read()
        except OSError:pass
    imports=[]
    if source is not None:
        try:work=deque(ast.iter_child_nodes(ast.parse(source,filename=filename)))
        except (SyntaxError,ValueError):work=deque()
        while work:
            node=work.popleft()
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Lambda)):continue
            if isinstance(node,ast.Import):
                for alias in node.names:imports.extend([alias.name,alias.name.split('.')[0]])
            elif isinstance(node,ast.ImportFrom):
                package=getattr(module,'__package__',None)
                if package is None:package=getattr(spec,'parent',None)
                try:
                    absolute=importlib.util.resolve_name('.'*node.level+(node.module or ''),package) if node.level else node.module or ''
                except (ImportError,ValueError):
                    # A static branch need not have executed. An unresolved
                    # relative import has no evaluated edge to add to this graph.
                    continue
                imports.append(absolute)
                imports.extend(absolute+'.'+alias.name for alias in node.names)
            else:work.extend(ast.iter_child_nodes(node))
    try:reference=weakref.ref(spec) if spec is not None else lambda:None
    except TypeError:return imports  # Unusual third-party spec: do not cache.
    _MODULE_IMPORTS[module]=(filename,reference,getattr(module,'_dsh_hmr_source',None),tuple(imports))
    return imports


def module_url(module):
    if not isinstance(module, types.ModuleType):
        return None
    filename = getattr(module, '__file__', None)
    if not isinstance(filename, str):
        return None
    previous = _MODULE_URLS.get(module)
    if previous is None or previous[0] != filename:
        previous = (filename, Path(os.path.realpath(filename)).as_uri())
        _MODULE_URLS[module] = previous
    return previous[1]


class FreshSourceLoader(importlib.machinery.SourceFileLoader):
    def exec_module(self, module):
        # Compile the actual source: same-size edits within one filesystem tick
        # must not read a still-valid timestamp-based .pyc from the old version.
        source = self.get_data(self.path)
        code = compile(source, self.path, 'exec')
        module._dsh_hmr_source = source
        module._dsh_hmr_links = []
        original_import = builtins.__import__
        def tracked_import(name, globals=None, locals=None, fromlist=(), level=0):
            imported = original_import(name, globals, locals, fromlist, level)
            absolute = importlib.util.resolve_name('.'*level+name, (globals or {}).get('__package__')) if level else name
            targets = [imported, sys.modules.get(absolute)]
            targets.extend(sys.modules.get(absolute+'.'+child) for child in (fromlist or ()) if isinstance(child, str))
            for target in targets:
                url = module_url(target)
                if url is not None and url not in module._dsh_hmr_links:
                    module._dsh_hmr_links.append(url)
            return imported
        module.__dict__['__builtins__'] = dict(vars(builtins), __import__=tracked_import)
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
    def __init__(self, urls, roots=()):
        self.urls = urls
        self.roots = roots

    def find_spec(self, fullname, path=None, target=None):
        if not self.urls and not self.roots:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is not None and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            filename = os.path.realpath(spec.origin)
            if Path(filename).as_uri() in self.urls or any(filename.startswith(root) for root in self.roots):
                spec.loader = FreshSourceLoader(fullname, spec.origin)
                return spec
        return None


@contextmanager
def source_imports(directory):
    """Capture executed imports of a Python Host package and its local modules."""
    finder = _FreshFinder(set(), (os.path.realpath(directory)+os.sep,))
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path[:] = [value for value in sys.meta_path if value is not finder]


class PythonModules:
    def __init__(self, ctx):
        self.ctx = ctx
        self._fresh_urls = set()
        self._finder = None
        self._snapshots = weakref.WeakKeyDictionary()
        self._host = None

    def loaded_modules(self):
        loader = self.ctx.get('loader')
        cache = getattr(getattr(loader, 'internal', None), 'loadCache', {})
        modules = {}
        for url, module in list(cache.items()):
            if isinstance(module, types.ModuleType):
                modules.setdefault(url, {})[id(module)] = module
        for module in list(sys.modules.values()):
            url = module_url(module)
            if url is not None:
                modules.setdefault(url, {})[id(module)] = module
        return {url:list(values.values()) for url, values in modules.items()}

    def loaded_urls(self):
        loader = self.ctx.get('loader')
        cache = getattr(getattr(loader, 'internal', None), 'loadCache', {})
        return list(dict.fromkeys([*cache, *self.loaded_modules()]))

    def _links(self, module):
        traced = getattr(module, '_dsh_hmr_links', None)
        if isinstance(traced, list):
            return list(traced)
        # Modules imported before tracing began keep a one-time syntax snapshot;
        # bindings to imported modules/classes/functions supplement those edges.
        if module not in self._snapshots:
            targets = [sys.modules.get(name) for name in _static_imports(module)]
            for value in list(module.__dict__.values()):
                if isinstance(value, types.ModuleType):
                    targets.append(value)
                elif isinstance(value, (types.FunctionType, types.MethodType, type)):
                    origin = value.__module__
                    if isinstance(origin, str) and origin != module.__name__:
                        targets.append(sys.modules.get(origin))
            self._snapshots[module] = list(dict.fromkeys(url for url in map(module_url, targets) if url is not None))
        return list(self._snapshots[module])

    def get_linked(self, url):
        return list(dict.fromkeys(child for module in self.loaded_modules().get(url, ()) for child in self._links(module)))

    def module_graph(self):
        importers = {}
        for url, modules in self.loaded_modules().items():
            for child in dict.fromkeys(child for module in modules for child in self._links(module)):
                importers.setdefault(child, {})[url] = None
        return {url:list(values) for url, values in importers.items()}

    async def module_graph_async(self, stopping):
        """Yield while inspecting older modules so shutdown can end planning."""
        importers = {}
        for url, modules in self.loaded_modules().items():
            await asyncio.sleep(0)
            if stopping():
                return None
            for child in dict.fromkeys(child for module in modules for child in self._links(module)):
                importers.setdefault(child, {})[url] = None
        return {url:list(values) for url, values in importers.items()}

    def host_modules(self):
        if self._host is None:
            filename = sys.argv[0] if sys.argv else None
            main = sys.modules.get('__main__')
            root = module_url(main)
            if not filename or not os.path.isfile(filename) or root != Path(os.path.realpath(filename)).as_uri():
                self._host = set()
            else:
                modules = self.loaded_modules()
                work, seen = [root], {root}
                for url in work:
                    for module in modules.get(url, ()):
                        for child in self._links(module):
                            if child not in seen:
                                seen.add(child)
                                work.append(child)
                self._host = seen
        return set(self._host)

    def external_modules(self):
        """The evaluated entry graph, stopping traversal at installed packages."""
        from dsh.cordis.hmr_changes import excluded
        main = module_url(sys.modules.get('__main__'))
        filename = sys.argv[0] if sys.argv else None
        if not filename or not os.path.isfile(filename) or main != Path(os.path.realpath(filename)).as_uri():
            return set()
        modules = self.loaded_modules()
        work, seen = [main], set()
        for url in work:
            if url in seen or excluded(url):
                continue
            seen.add(url)
            for module in modules.get(url, ()):
                work.extend(self._links(module))
        return seen

    def plugins_of(self, url):
        loader = self.ctx.get('loader')
        values = []
        for module in self.loaded_modules().get(url, ()):
            exported = loader.unwrap_exports(module)
            if self.ctx.registry.resolve(exported) is not None:
                values.append(exported)
            # Native :Export and dsh.python descriptors can expose several
            # classes from one Python module; include actual running exports.
            for value in list(module.__dict__.values()):
                if isinstance(value, (type, types.FunctionType)) and self.ctx.registry.get(value) is not None:
                    values.append(value)
        result = {}
        for value in values:
            result.setdefault(id(self.ctx.registry.resolve(value)), value)
        return list(result.values())

    def dispose(self):
        if self._finder is not None:
            sys.meta_path[:] = [finder for finder in sys.meta_path if finder is not self._finder]
            self._finder = None
        self._fresh_urls.clear()
        self._snapshots.clear()
        self._host = None

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
