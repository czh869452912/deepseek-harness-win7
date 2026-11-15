"""Replace evaluated module generations while retaining entry ownership."""
import asyncio
import inspect
import os
import sys
import types
from pathlib import Path

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.hmr_changes import excluded
from dsh.cordis.hmr_modules import module_url
from dsh.cordis.hmr_paths import file_path


async def dependencies(hmr, url, ignored):
    result = {}
    async def visit(current):
        if current in ignored or current in result or excluded(current):
            return
        result[current] = None
        children = await hmr.getLinked(current)
        await asyncio.gather(*(visit(child) for child in children))
    await visit(url)
    return list(result)


def _location(namespace, cache):
    for url, value in reversed(list(cache.items())):
        if value is namespace:
            return url, None
    # Native :Export and descriptor entries retain a class/function namespace.
    if isinstance(namespace, (type, types.FunctionType)):
        module = sys.modules.get(namespace.__module__)
        url = module_url(module)
        if url in cache and getattr(module, namespace.__name__, None) is namespace:
            return url, namespace.__name__
    return None, None


def _unloaded_location(hmr, name, base):
    if name.startswith('cordis:'):
        return name
    from dsh.cordis.loader import resolve_module_specifier
    packages = hmr.ctx.get('pluginPackages')
    if packages is not None:
        filename = packages.resolveResource(name, base)
    else:
        filename = resolve_module_specifier(name, file_path(base), getattr(hmr.ctx.loader, 'installation_module_roots', None))
    if filename is None:
        raise ImportError('Cannot locate module '+name)
    return Path(os.path.realpath(filename)).as_uri()


async def partial_reload(hmr):
    await hmr.analyzeChanges()
    loader, registry = hmr.ctx.loader, hmr.ctx.registry
    cache = loader.internal.loadCache
    # A name may represent several already evaluated namespaces after a package
    # mapping change. Resolve those identities without consulting the new map.
    names = {}
    for entry in loader.entries():
        base = getattr(entry.parent.tree.ctx, 'baseUrl', None)
        if base is None:
            raise RuntimeError('HMR entry tree has no base URL')
        name = entry.options.get('name')
        if name is None:
            continue
        namespace = getattr(entry, 'moduleNamespace', None)
        names.setdefault((base, name), {})[id(namespace)] = namespace
    pending, originally_declined = {}, set(hmr.declined)
    for (base, name), namespaces in names.items():
        for namespace in namespaces.values():
            if namespace is None and len(namespaces) > 1:
                continue
            try:
                url, selector = _location(namespace, cache) if namespace is not None and not name.startswith('cordis:') else (_unloaded_location(hmr, name, base), None)
                if url is None:
                    raise RuntimeError('HMR cannot locate the loaded module for '+name+' from '+base)
                if url in hmr.declined and not (selector is not None and url not in originally_declined):
                    continue
                module = cache.get(url)
                plugin = namespace if selector is not None else loader.unwrap_exports(module)
                if module is None or registry.resolve(plugin) is None:
                    continue
                pending[(url, selector)] = dict(filename=url, namespace=namespace if selector is not None else module,
                                               plugin=plugin, selector=selector, module_name=getattr(module, '__name__', None))
                hmr.declined[url] = None
            except Exception as error:
                hmr.ctx.logger.warn(error)
    reloads = {}
    def include(record, runtime):
        info = reloads.get(record['plugin'])
        if info is None and runtime is not None:
            info = next((value for value in reloads.values() if value['runtime'] is runtime), None)
        if info is None:
            return False
        info['modules'][id(record['namespace'])] = record
        return True
    for key, record in list(pending.items()):
        url, plugin = record['filename'], record['plugin']
        hmr.declined.pop(url, None)
        linked = await dependencies(hmr, url, hmr.declined)
        hmr.declined[url] = None
        if not linked:
            pending.pop(key)
            continue
        if not any(child in hmr.accepted for child in linked):
            continue
        hmr.accepted.update(dict.fromkeys(linked))
        runtime = registry.get(plugin)
        if include(record, runtime):
            continue
        reloads[plugin] = dict(filename=url, runtime=runtime, modules={id(record['namespace']):record})
    for record in pending.values():
        if include(record, registry.get(record['plugin'])):
            hmr.accepted[record['filename']] = None
    rollback = hmr.modules.evict(hmr.accepted)
    generations = []
    for previous, info in reloads.items():
        fibers = []
        for fiber in list(getattr(info['runtime'], 'fibers', ())):
            entry = getattr(fiber, 'entry', None)
            wrapper = getattr(entry, 'fiber', None)
            if wrapper is None or wrapper.ctx.fiber is not fiber:
                entry = None
            fibers.append(dict(fiber=fiber, entry=entry, config=fiber.rawConfig if entry is None else entry.options.get('config'),
                               namespace=None if entry is None else getattr(entry, 'moduleNamespace', None)))
        generations.append(dict(info, previous=previous, fibers=fibers))
    attempts = []
    try:
        for generation in generations:
            replacements = {}
            for identity, record in generation['modules'].items():
                if record['selector'] is not None:
                    from dsh.cordis.hmr_modules import load_python_file
                    namespace = load_python_file(file_path(record['filename']), record['module_name'])
                    cache[record['filename']] = namespace
                else:
                    namespace = loader.import_plugin(record['filename'])
                if inspect.isawaitable(namespace):
                    namespace = await namespace
                if record['selector'] is not None:
                    namespace = getattr(namespace, record['selector'])
                replacements[identity] = dict(record, namespace=namespace, plugin=loader.unwrap_exports(namespace))
            first = next(iter(replacements.values()))
            attempts.append(dict(generation, replacement=first['plugin'], replacements=replacements, activated=[]))
    except Exception:
        rollback()
        raise

    async def reload(plugin, fibers, replacements=None, activated=None):
        replacements = replacements or {}
        activated = [] if activated is None else activated
        callbacks = {registry.resolve(value['plugin']) for value in replacements.values()}
        implementations = []
        for previous in fibers:
            if previous['entry'] is None:
                implementation = plugin
            else:
                replacement = replacements.get(id(previous['namespace']))
                implementation = replacement['plugin'] if replacement is not None else loader.unwrap_exports(previous['namespace'])
                callbacks.add(registry.resolve(implementation))
            implementations.append((previous, implementation))
        for previous, implementation in implementations:
            fiber = previous['fiber']
            if fiber.parent.fiber.uid is None:
                continue
            if previous['entry'] is None and len(callbacks) > 1:
                raise RuntimeError('HMR replacement is ambiguous for a plugin instance without a Loader entry')
            if previous['entry'] is not None:
                module_name = implementation.__name__ if isinstance(implementation, types.ModuleType) else getattr(implementation, '__module__', None)
                if module_name in sys.modules:
                    previous['entry']._loaded_module_name = module_name
            wrapper = fiber.parent.registry.plugin(implementation, previous['config'])
            actual = wrapper.ctx.fiber
            if previous['entry'] is not None:
                actual.entry = previous['entry']
                previous['entry'].fiber = wrapper
            activated.append(actual)
        await asyncio.gather(*(fiber.await_() for fiber in activated))

    removed = set()
    try:
        for attempt in attempts:
            if attempt['runtime'] is None:
                continue
            previous = attempt['previous']
            removed.add(previous)
            try:
                registry.delete(previous)
                await asyncio.gather(*(item['fiber'].await_() for item in attempt['fibers']))
            except Exception as error:
                hmr.ctx.logger.warn(error)
            await await_callback_result(reload(attempt['replacement'], attempt['fibers'], attempt['replacements'], attempt['activated']))
    except Exception:
        rollback()
        for attempt in attempts:
            if attempt['previous'] not in removed:
                continue
            try:
                for fiber in attempt['activated']:
                    runtime = fiber.runtime
                    if runtime is not None and registry.get(runtime.callback) is runtime:
                        replacement_fibers = list(runtime.fibers)
                        registry.delete(runtime.callback)
                        await asyncio.gather(*(value.await_() for value in replacement_fibers), return_exceptions=True)
                await await_callback_result(reload(attempt['previous'], attempt['fibers']))
            except Exception as error:
                hmr.ctx.logger.warn(error)
        raise
    await loader.await_()
    for attempt in attempts:
        for original, replacement in attempt['replacements'].items():
            for entry in loader.entries():
                if id(getattr(entry, 'moduleNamespace', None)) == original:
                    entry.moduleNamespace = replacement['namespace']
    hmr.ctx.emit('hmr/reload', reloads)
    hmr.files.refresh(hmr.accepted)
    hmr._stashed = {}
