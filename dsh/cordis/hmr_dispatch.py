"""Classify a debounced file batch inside the service's shared transaction."""
import inspect
import os
from pathlib import Path


async def dispatch(hmr):
    if hmr._application_ready is not None and not await hmr._application_ready:
        return
    batch = list(hmr._changed)
    hmr._changed.clear()
    loader = hmr.ctx.loader
    includes, full_reload = [], False
    for path in batch:
        configured = os.path.abspath(os.path.join(hmr.base_dir, path))
        filename = os.path.realpath(os.path.join(hmr.watch_base_dir, path))
        if filename in hmr._config_paths or configured in hmr._config_paths:
            continue
        manifest = os.path.basename(filename) == 'package.json' and 'node_modules' not in Path(filename).parts
        if manifest:
            hmr.invalidate_manifest(filename)
        url = Path(filename).as_uri()
        if url in hmr.externals:
            full_reload = True
            continue
        cache = getattr(getattr(loader, 'internal', None), 'loadCache', None)
        if cache is not None and url in cache:
            hmr._stashed[url] = None
            continue
        if manifest:
            continue
        include = next((entry.subtree for entry in loader.entries()
                        if getattr(entry.subtree, 'filename', None) in (filename, configured)), None)
        if include is not None:
            if include not in includes:
                includes.append(include)
        else:
            hmr.ctx.emit('hmr/change', url)
    if full_reload:
        loader.exit()
        return
    if not includes and not hmr._stashed:
        return
    for include in includes:
        try:
            result = include.refresh()
            if inspect.isawaitable(result):
                await result
        except Exception as error:
            hmr.ctx.logger.warn(error)
    if hmr._stashed:
        try:
            await hmr.partialReload()
        finally:
            hmr._stashed.clear()
    await loader.await_()
