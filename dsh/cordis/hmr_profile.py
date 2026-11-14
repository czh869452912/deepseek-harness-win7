"""Profile-wide module replacement and settled generation recomposition."""
import asyncio
import importlib
import inspect
import os

from dsh.boot.runtime_resolution import _field
from dsh.cordis.fiber import FiberState
from dsh.cordis.hmr_paths import file_path, package_manifests, profile_roots
from dsh.cordis.hmr_plan import plan_replacement


def mapped_directories(resolution):
    if resolution is None:
        return set()
    directories = [_field(entry, 'packageDir') for entry in _field(resolution, 'entries', ())
                   if _field(entry, 'scope') == 'profile']
    directories.extend(_field(root, 'realPath') for root in _field(resolution, 'linkedRoots', ()))
    return {(os.path.realpath(directory) if os.path.exists(directory) else directory)+os.sep for directory in directories}


async def _contained(hmr, step, operation, fallback):
    try:
        result = operation()
        return await result if inspect.isawaitable(result) else result
    except Exception as error:
        hmr.ctx.logger.warn('%s failed; module replacement was not completed', step)
        hmr.ctx.logger.warn(error)
        return fallback


def _invalidate_manifest(hmr, filename):
    # Python's explicit resource/descriptor resolvers read manifests afresh.
    # Directory finder caches still need expiring after a package is installed.
    importlib.invalidate_caches()


async def stop_planned(hmr, plan):
    for manifest in plan['manifests']:
        _invalidate_manifest(hmr, manifest)
    hmr.modules.evict(plan['evicted'])
    await asyncio.gather(*(hmr.ctx.registry.delete_async(plugin) for plugin in plan['plugins']), return_exceptions=True)
    await asyncio.gather(*(fiber.await_() for fiber in plan['fibers']), return_exceptions=True)


async def reconcile_profile(hmr, required_ids=()):
    if not hmr._executing.get():
        raise RuntimeError('HMR profile reconciliation must run inside runExclusive')
    profile = hmr._owner_context.get('profileContext')
    if profile is None:
        raise RuntimeError('HMR profile reconciliation requires profileContext')
    running = [entry for entry in hmr.ctx.loader.entries() if entry.fiber is not None and entry.fiber.state == FiberState.ACTIVE]
    packages = hmr._owner_context.get('pluginPackages')
    mapped = mapped_directories(getattr(packages, 'resolution', None))
    comparison, compared_at, pending = None, 0, []
    try:
        from dsh.boot.profile_context import read_profile_patches
        from dsh.boot.recomposition import recompose_profile
        patches = read_profile_patches('dsh', profile)
        compared_at = hmr.files.now()
        def compare():
            roots = profile_roots(_field(profile, 'dir'))
            return dict(roots=roots, **hmr.files.compare(hmr._profile_modules(roots)))
        comparison = await _contained(hmr, 'comparing loaded modules with disk', compare, None)
        # Retain loaded URL discovery order rather than Python set order.
        if comparison is not None:
            pending = [dict(url=url, reason='module-comparison') for url in hmr._profile_modules(comparison['roots']) if url in comparison['stale']]
        cache = getattr(getattr(hmr.ctx.loader, 'internal', None), 'loadCache', None)
        unavailable = cache is None
        if not unavailable and comparison is not None and pending:
            async def plan_and_stop():
                plan = plan_replacement(hmr.ctx, [item['url'] for item in pending], comparison['roots'],
                    hmr.modules.module_graph(), hmr.modules.host_modules(), hmr.modules.plugins_of)
                await stop_planned(hmr, plan)
                return plan['pending']
            pending = await _contained(hmr, 'planning module replacement', plan_and_stop, pending)

        def expire_failed():
            if unavailable:
                return
            roots = comparison['roots'] if comparison is not None else [os.path.realpath(_field(profile, 'dir'))+os.sep]
            for root in roots:
                _invalidate_manifest(hmr, os.path.join(root, 'package.json'))
            hmr.modules.evict([url for url in hmr._profile_modules(roots) if url in cache and cache[url] is None])
        await _contained(hmr, 'expiring failed imports', expire_failed, None)
        result = await recompose_profile(hmr._owner_context.root, patches, 'dsh', dict(requiredIds=list(required_ids), running=running))
        restart = 'module-comparison' if comparison is None or unavailable else result.get('restartReason')
        return dict(warnings=result['warnings'], pending=pending, **({} if restart is None else dict(restartReason=restart)))
    finally:
        def evict_dropped():
            kept = mapped_directories(getattr(packages, 'resolution', None))
            dropped = [directory for directory in mapped if directory not in kept]
            if not dropped:
                return
            host = hmr.modules.host_modules()
            urls = [url for url in hmr._profile_modules(dropped) if url not in host
                    and not any(file_path(url).startswith(directory) for directory in kept)]
            for url in urls:
                for manifest in package_manifests(url, dropped):
                    _invalidate_manifest(hmr, manifest)
            hmr.modules.evict(urls)
        await _contained(hmr, 'evicting dropped packages', evict_dropped, None)
        def record():
            if comparison is not None:
                hmr.files.observe(hmr._profile_modules(comparison['roots']),
                    dict(seen=comparison['seen'], retained={item['url'] for item in pending}, at=compared_at))
        await _contained(hmr, 'recording loaded module files', record, None)
