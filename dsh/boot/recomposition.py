"""Settled profile reconciliation over the launcher's complete patch stack."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urljoin
from dsh.boot.compatibility_preflight import prepare_profile_patches
from dsh.boot.startup import inactive_entries, inactive_diagnostic, activation_diagnostic


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
    from dsh.boot.app_boot import _bootstrap_includes
    entry = _bootstrap_includes.get(ctx)
    if entry is None:
        raise RuntimeError(bin_name+': profile reload requires the root Include entry')
    previous = [_record(row) for row in await inactive_entries(ctx, False)]
    fibers = [row.fiber for row in ctx.loader.entries() if row.fiber is not None]
    include_config = {key:value for key,value in entry.options['config'].items() if key != 'patches'}
    base = getattr(entry.parent.tree.ctx, 'baseUrl', None)
    if base is None:
        base = Path.cwd().as_uri()+'/'
    parent_url = urljoin(urljoin(base, include_config['path']), '.')
    prepared = prepare_profile_patches(ctx, patches, parent_url, bin_name)
    await entry.update(dict(config=dict(include_config, patches=prepared)))
    # Removed rows leave Loader immediately; their owned disposers still need
    # joining even though Loader.getTasks can no longer find them.
    await asyncio.gather(*(fiber.await_() for fiber in fibers), return_exceptions=True)
    await ctx.loader.await_()
    failures = await inactive_entries(ctx)
    introduced = [failure for failure in failures if failure['entry'].options['id'] in required_ids
        or (failure['outcome']['kind'] != 'pending' and not any(_same(row, failure) for row in previous))]
    if introduced:
        raise RuntimeError(activation_diagnostic(bin_name, introduced, False).rstrip())
    ctx.emit('app-boot/config-reload')
    return [inactive_diagnostic(failure, False) for failure in failures]


reconcileProfilePatches = reconcile_profile_patches
