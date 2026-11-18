"""Settled profile reconciliation over the launcher's complete patch stack."""
import asyncio
import copy
import json
from pathlib import Path
from urllib.parse import urljoin
from dsh.boot.compatibility_preflight import prepare_profile_patches
from dsh.boot.startup import inactive_entries, inactive_diagnostic, activation_diagnostic
from dsh.boot.runtime_resolution import ProfileRuntimeResolution, _field
from dsh.boot.plugin_packages import ResolutionRestartRequired
from dsh.cordis.fiber import FiberState
from dsh.cordis.loader import apply_entry_patches


def _options(entry):
    return json.dumps(entry.options, ensure_ascii=False, separators=(',', ':'))


def _record(failure):
    entry = failure['entry']
    return dict(entry=entry, fiber=entry.fiber, options=_options(entry),
        diagnostic=inactive_diagnostic(failure, False) if entry.fiber is not None and entry.fiber.uid else None)


def _same(previous, failure):
    entry = failure['entry']
    return (previous['entry'] is entry and previous['fiber'] is entry.fiber and previous['options'] == _options(entry)
        and (previous['diagnostic'] is None or previous['diagnostic'] == inactive_diagnostic(failure, False)))


async def reconcile_profile_patches(ctx, patches, bin_name, required_ids=()):
    """Apply all layers; reject new/changed failures and warn for unchanged ones.

    This boundary deliberately keeps runtime mappings and existing import
    failures intact. Full package-generation recomposition is a separate API.
    """
    return (await _recompose(ctx, patches, bin_name, dict(requiredIds=required_ids), False))['warnings']


async def recompose_profile(ctx, patches, bin_name, options=None):
    """Stop dropped rows, publish one successor, apply and judge activation."""
    return await _recompose(ctx, patches, bin_name, options or {}, True)


def _row_ids(patches):
    ids = set()
    def visit(rows):
        for row in rows:
            ids.add(row.get('id'))
            if (row.get('group') is True or row.get('name') == 'cordis:group') and isinstance(row.get('config'), list):
                visit(row['config'])
    visit(apply_entry_patches([], copy.deepcopy(patches), lambda *args: None))
    return ids


def _import_failed(row):
    try:
        enabled = not row.disabled
    except Exception:
        return False
    return enabled and row.parent.ctx.fiber.uid is not None and (row.fiber is None or row.fiber.state == FiberState.DISPOSED)


async def _resume(ctx, rows):
    if _stopping(ctx):
        return
    entries = set(ctx.loader.entries())
    for row in rows:
        if row in entries and (row.fiber is None or not row.fiber.uid):
            await row.update({}, False, True)
    await _await_loader(ctx)


def _stopping(ctx):
    return ctx.fiber.uid is None or ctx.fiber.state == FiberState.UNLOADING or ctx.get('loader') is None


async def _await_loader(ctx):
    """Do not make a reload await the teardown that is draining that reload.

    Python lifecycle tasks may still be queued when a newly provided value is
    visible to another task. Root disposal ends admission; the root continues
    to own the pending Loader join through final resource settlement.
    """
    if _stopping(ctx):
        return
    loop = asyncio.get_running_loop()
    stopping = loop.create_future()
    def disposed(fiber, previous):
        if fiber is ctx.fiber and _stopping(ctx) and not stopping.done():
            stopping.set_result(None)
    dispose = ctx.on('internal/status', disposed, global_listener=True)
    task = loop.create_task(ctx.loader.await_())
    async def owned():
        await asyncio.shield(task)
    ctx.fiber.schedule_settlement(owned())
    try:
        await asyncio.wait([task, stopping], return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            task.result()
    finally:
        dispose()


def _table(resolution):
    return json.dumps([_field(resolution, name) for name in ('localPackageNames', 'entries', 'linkedRoots')],
        ensure_ascii=False, separators=(',', ':'))


async def _recompose(ctx, patches, bin_name, options, with_resolution):
    # A fresh Context without Loader is not a retiring application. Let _apply
    # report the missing bootstrap Include; only actual root teardown is a no-op.
    if ctx.fiber.uid is None or ctx.fiber.state == FiberState.UNLOADING:
        return dict(warnings=[])
    applying = False
    stopped = []
    running = options.get('running', [])
    def mark_applying():
        nonlocal applying
        applying = True
    try:
        return await _apply(ctx, patches, bin_name, options, with_resolution, stopped, mark_applying)
    finally:
        if not applying and not _stopping(ctx) and (stopped or running):
            try:
                for group, row, index in sorted(stopped, key=lambda item: item[2]):
                    group.data.insert(index, row)
                    await group.create(row)
                await _resume(ctx, running)
                ran = {row.options['id'] for row in running}
                for failure in await inactive_entries(ctx):
                    if failure['entry'].options['id'] in ran:
                        ctx.logger.warn(bin_name+': '+inactive_diagnostic(failure, False))
            except Exception as error:
                ctx.logger.warn(error)

async def _apply(ctx, patches, bin_name, options, with_resolution, stopped, mark_applying):
    from dsh.boot.app_boot import _bootstrap_includes
    entry = _bootstrap_includes.get(ctx)
    if entry is None:
        raise RuntimeError(bin_name+': profile reload requires the root Include entry')
    previous = [_record(row) for row in await inactive_entries(ctx, False)]
    fibers = [row.fiber for row in ctx.loader.entries() if row.fiber is not None]
    include_config = {key:value for key,value in entry.options['config'].items() if key != 'patches'}
    packages = ctx.get('pluginPackages') if with_resolution else None
    current = packages.resolution if packages is not None else None
    successor = await current.compute_latest_resolution() if isinstance(current, ProfileRuntimeResolution) else None
    if successor is not None:
        listed = _row_ids(patches)
        composed = _row_ids(entry.options['config'].get('patches', []))
        tree = entry.subgroup.tree if entry.subgroup is not None else None
        dropped = [row for row in ctx.loader.entries() if row.parent.tree is tree and row.options['id'] in composed and row.options['id'] not in listed]
        ids = {row.options['id'] for row in dropped}
        topmost = []
        for row in dropped:
            parent_entry = getattr(row.parent.ctx.fiber, 'entry', None)
            if parent_entry is None or parent_entry.options['id'] not in ids:
                topmost.append(row)
        for row in topmost:
            index = next((i for i, item in enumerate(row.parent.data) if item is row.options), -1)
            stopped.append((row.parent, copy.deepcopy(row.options), index))
        if topmost:
            dropped_fibers = [row.fiber for row in dropped if row.fiber is not None]
            for row in topmost:
                row.options['disabled'] = True
                row.parent.remove(row.options['id'])
            await asyncio.gather(*(fiber.await_() for fiber in dropped_fibers), return_exceptions=True)
            await _await_loader(ctx)
        try:
            if _table(current) != _table(successor):
                packages.replace(successor)
        except ResolutionRestartRequired:
            return dict(warnings=[], restartReason='package-moved')
    base = getattr(entry.parent.tree.ctx, 'baseUrl', None)
    if base is None:
        base = Path.cwd().as_uri()+'/'
    parent_url = urljoin(urljoin(base, include_config['path']), '.')
    prepared = prepare_profile_patches(ctx, patches, parent_url, bin_name)
    mark_applying()
    running = options.get('running', [])
    retried = list(dict.fromkeys(list(running) + ([row for row in ctx.loader.entries() if _import_failed(row)] if with_resolution else [])))
    prior_data = {row: row.parent.data for row in retried}
    try:
        await entry.update(dict(config=dict(include_config, patches=prepared)))
    finally:
        await _resume(ctx, [row for row in retried if row.parent.data is prior_data[row]])
    if _stopping(ctx):
        return dict(warnings=[])
    # Removed rows leave Loader immediately; their owned disposers still need
    # joining even though Loader.getTasks can no longer find them.
    await asyncio.gather(*(fiber.await_() for fiber in fibers), return_exceptions=True)
    await _await_loader(ctx)
    if _stopping(ctx):
        return dict(warnings=[])
    failures = await inactive_entries(ctx)
    introduced = [failure for failure in failures if failure['entry'].options['id'] in options.get('requiredIds', [])
        or (failure['outcome']['kind'] != 'pending' and (failure['entry'] in running or not any(_same(row, failure) for row in previous)))]
    if introduced:
        raise RuntimeError(activation_diagnostic(bin_name, introduced, False).rstrip())
    ctx.emit('app-boot/config-reload')
    return dict(warnings=[inactive_diagnostic(failure, False) for failure in failures])


reconcileProfilePatches = reconcile_profile_patches
recomposeProfile = recompose_profile
