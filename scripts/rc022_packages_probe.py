"""Pair metadata routes, cache ownership and generation publication with Source."""
import copy
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None
REQUESTS = ['', 'fs', 'fs/promises', 'fs/other', 'node:test', '@scope', '@scope/pkg/sub', './a', '/a', '\\a', '#alias', 'http:a', 'core', 'private', 'absent']
MODES = ['native', 'active', 'sibling', 'outside-profile', 'nested', 'local-empty', 'declared-local', 'self', 'invalid', 'linked-peer', 'linked-local', 'linked-deep', 'linked-unlisted', 'installation-overlap', 'cache', 'cache-absence']
REPLACEMENTS = ['same', 'profile-version', 'profile-declarer', 'profile-remove', 'profile-move', 'installation-remove', 'installation-version', 'installation-declarer', 'installation-move', 'scope', 'local-add', 'local-remove', 'new', 'profiles-dir', 'profile-dir']


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output / 'input.json'
    path.write_text(json.dumps(dict(requests=REQUESTS, modes=MODES, replacements=REPLACEMENTS)), encoding='utf-8')
    return [path]


def pkg(path, name, **fields):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'package.json').write_text(json.dumps(dict(name=name, version='1.0.0', **fields)), encoding='utf-8')


def fixture(root, mode):
    active = root / 'profiles/active'
    active.mkdir(parents=True)
    entry = dict(name='core', packageDir=str(root / 'installation/node_modules/core'), declarer=str(root / 'installation/package.json'), version='1.0.0', scope='installation')
    private = dict(name='private', packageDir=str(root / 'selected/node_modules/private'), declarer=str(root / 'selected/package.json'), version='1.0.0', scope='profile')
    for row in (entry, private):
        pkg(Path(row['packageDir']), row['name'])
    pkg(root / 'node_modules/absent', 'fallback')
    table = dict(profilesDir=str(root / 'profiles'), profileDir=str(active), localPackageNames=[], entries=[entry, private], linkedRoots=[])
    parent = active / 'caller.mjs'
    if mode in ('native', 'linked-unlisted'):
        parent = root / 'outside/caller.mjs'
    if mode == 'sibling':
        parent = root / 'profiles/sibling/caller.mjs'
    if mode == 'outside-profile':
        table['profileDir'] = str(root / 'custom'); parent = root / 'custom/caller.mjs'
    if mode in ('nested', 'local-empty', 'self', 'invalid'):
        owner = active / 'node_modules/owner'
        pkg(owner, 'core' if mode == 'self' else 'owner', **({'exports': './index.mjs'} if mode == 'self' else {}))
        parent = owner / 'caller.mjs'
        if mode == 'nested':
            pkg(owner / 'node_modules/core', 'nested')
        if mode == 'local-empty':
            (owner / 'node_modules/core').mkdir(parents=True)
        if mode == 'invalid':
            (owner / 'package.json').write_text('{', encoding='utf-8')
    if mode == 'declared-local':
        table['localPackageNames'] = ['core']; pkg(active / 'node_modules/core', 'direct')
    if mode.startswith('linked-') or mode == 'installation-overlap':
        linked = root / 'external'
        pkg(linked, 'external', peerDependencies={'core': '*'})
        table['linkedRoots'] = [dict(name='external', realPath=str(linked))]
        parent = linked / 'caller.mjs'
        if mode in ('linked-peer', 'linked-local'):
            pkg(linked / 'node_modules/core', 'physical-peer')
        if mode == 'linked-local':
            pkg(linked, 'external')
        if mode == 'linked-deep':
            parent = linked / 'nested/caller.mjs'; pkg(linked / 'nested/node_modules/core', 'deep')
        if mode == 'linked-unlisted':
            table['entries'] = []
        if mode == 'installation-overlap':
            entry['packageDir'] = str(linked); pkg(linked / 'node_modules/core', 'own-installation')
    if mode == 'cache-absence':
        Path(entry['packageDir']).rename(root / 'empty-old')
        Path(entry['packageDir']).mkdir()
    return table, parent.as_uri()


def successor(table, mode):
    value = copy.deepcopy(table)
    if mode.startswith('profile-') and mode != 'profile-dir':
        row = value['entries'][1]; field = mode[len('profile-'):]
        if field == 'remove': value['entries'].pop()
        elif field == 'move': row['packageDir'] += '-moved'
        elif field == 'declarer': row['declarer'] += '-changed'
        elif field == 'version': row['version'] = '2.0.0'
    elif mode.startswith('installation-'):
        row = value['entries'][0]; field = mode[len('installation-'):]
        if field == 'remove': value['entries'].pop(0)
        elif field == 'move': row['packageDir'] += '-moved'
        elif field == 'declarer': row['declarer'] += '-changed'
        elif field == 'version': row['version'] = '2.0.0'
    elif mode == 'scope': value['entries'][1]['scope'] = 'installation'
    elif mode == 'local-add': value['localPackageNames'] = ['core', 'private']
    elif mode == 'local-remove': value['localPackageNames'] = []
    elif mode == 'new': value['entries'].append(dict(value['entries'][1], name='new'))
    elif mode == 'profiles-dir': value['profilesDir'] += '-changed'
    elif mode == 'profile-dir': value['profileDir'] += '-changed'
    return value


async def native():
    from dsh.boot.plugin_packages import PluginPackages, bare_package_name, ResolutionRestartRequired
    from dsh.cordis import Context
    result = [dict(request=request, name=bare_package_name(request)) for request in REQUESTS]
    for mode in MODES:
        root = OUTPUT / 'files/native' / mode
        table, parent = fixture(root, mode)
        ctx = Context(); service = PluginPackages(ctx, {} if mode == 'native' else dict(resolution=table))
        row = dict(mode=mode, packages={})
        try:
            for name in ('core', 'core/feature', 'private', 'absent'):
                value = service.packageOf(name, parent)
                row['packages'][name] = value
            first = service.packageOf('core', parent)
            row['shared'] = first is service.packageOf('core/other', parent)
            if mode in ('cache', 'cache-absence'):
                pkg(Path(table['entries'][0]['packageDir']), 'edited')
                row['cached'] = service.packageOf('core', parent)
                service.replace(copy.deepcopy(table))
                row['replacement'] = service.packageOf('core', parent)
        finally:
            await ctx.fiber.dispose()
        result.append(json.loads(json.dumps(row).replace(str(root).replace('\\', '\\\\'), '$ROOT')))
    for mode in REPLACEMENTS:
        root = OUTPUT / 'files/native' / ('replace-' + mode)
        table, parent = fixture(root, 'active')
        if mode == 'local-remove': table['localPackageNames'] = ['core']
        ctx = Context(); service = PluginPackages(ctx, dict(resolution=table)); first = service.packageOf('core', parent)
        next_value = successor(table, mode)
        try:
            service.replace(next_value); error = None; restart = False
        except Exception as failure:
            error = str(failure); restart = isinstance(failure, ResolutionRestartRequired)
        result.append(dict(mode='replace-' + mode, error=error, restart=restart,
            published=service.resolution is next_value, same_cache=service.packageOf('core', parent) is first))
        await ctx.fiber.dispose()
    return result


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_packages.mts', 'Package metadata ownership, cache and atomic successor publication; no Python module-load or worker parity claim.',
        [Path(__file__).resolve(), ROOT / 'dsh/boot/plugin_packages.py'], prepare, node_args=('--expose-internals',))
