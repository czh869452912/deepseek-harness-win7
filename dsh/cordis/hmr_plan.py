"""Read-only replacement planning; cache mutation belongs to the executor."""
from dsh.cordis.hmr_paths import package_manifests


def _unique(values):
    return list({id(value): value for value in values}.values())


def plan_replacement(ctx, stale, roots, importers, host, plugins_of):
    """Keep host/unmanaged code loaded and plan the remaining transitive users.

    Returned collections preserve discovery order. No runtime, entry, module
    cache or manifest cache is changed at this boundary.
    """
    managed = {id(entry) for entry in ctx.loader.entries()}
    pending, evicted, manifests, plugins, fibers = [], {}, {}, {}, {}
    for url in stale:
        affected = dict.fromkeys([url])
        work = [url]
        index = 0
        while index < len(work):
            for importer in importers.get(work[index], ()):
                if importer not in affected:
                    affected[importer] = None
                    work.append(importer)
            index += 1
        running = []
        for plugin in _unique(plugin for module in affected for plugin in plugins_of(module)):
            runtime = ctx.registry.get(plugin)
            running.extend((plugin, fiber) for fiber in getattr(runtime, 'fibers', ()))
        affected_fibers = {id(fiber) for plugin, fiber in running}

        def owner(fiber):
            current = fiber
            while current.uid != 0:
                entry = getattr(current, 'entry', None)
                wrapper = getattr(entry, 'fiber', None)
                if (getattr(getattr(wrapper, 'ctx', None), 'fiber', None) is current
                        and id(entry) in managed and id(current) in affected_fibers):
                    return entry
                current = current.parent.fiber
            return None

        reason = ('host-module' if any(module in host for module in affected)
                  else 'unmanaged-plugin' if any(owner(fiber) is None for plugin, fiber in running) else None)
        if reason is not None:
            pending.append(dict(url=url, reason=reason))
            continue
        for manifest in package_manifests(url, roots):
            manifests[manifest] = None
        for module in affected:
            evicted[module] = None
        for plugin, fiber in running:
            plugins[id(plugin)] = plugin
            fibers[id(fiber)] = fiber
    return dict(pending=pending, evicted=list(evicted), manifests=list(manifests),
                plugins=list(plugins.values()), fibers=list(fibers.values()))
