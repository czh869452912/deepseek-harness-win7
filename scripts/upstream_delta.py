import argparse
from collections import deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def git(repository, *arguments):
    environment = dict(os.environ, GIT_OPTIONAL_LOCKS='0')
    completed = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
        '-c', 'core.untrackedCache=false', '-C', str(repository)] + list(arguments),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, check=False)
    if completed.returncode:
        raise ValueError('Read-only Git operation failed: ' + completed.stderr.decode('utf-8', 'replace').strip())
    return completed.stdout


def revision(repository, ref):
    if not isinstance(ref, str) or not ref or '\0' in ref:
        raise ValueError('A nonempty Git revision is required')
    return git(repository, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode('ascii').strip()


def source_state(repository):
    return dict(head=revision(repository, 'HEAD'), status=git(repository, 'status', '--porcelain=v1', '-z'))


def path_owner(path, manifests):
    candidates = [row for row in manifests if path == row['relative_manifest']
                  or row['relative_owner'] == '.' or path.startswith(row['relative_owner'] + '/')]
    return max(candidates, key=lambda row: len(row['relative_owner'])) if candidates else None


def changes(repository, base, target):
    return parse_changes(git(repository, 'diff', '--no-ext-diff', '--no-textconv', '--name-status', '-z',
        '--find-renames', base, target, '--'))


def parse_changes(data):
    fields = data.split(b'\0')
    if fields[-1] != b'':
        raise ValueError('Git change stream has no NUL terminator')
    fields.pop()
    rows = []
    offset = 0
    while offset < len(fields):
        status = fields[offset].decode('ascii')
        if not re.fullmatch(r'[ADMTUXB]|[RC](?:100|[0-9]{1,2})', status):
            raise ValueError('Git change status is unsupported')
        size = 3 if status.startswith(('R', 'C')) else 2
        if offset + size > len(fields):
            raise ValueError('Git change stream is incomplete')
        paths = [value.decode('utf-8', 'surrogateescape') for value in fields[offset + 1:offset + size]]
        if any(not path or PurePosixPath(path).is_absolute() or '..' in PurePosixPath(path).parts for path in paths):
            raise ValueError('Git change path is not repository-relative')
        rows.append(dict(status=status, before=paths[0] if status != 'A' else None,
                         after=paths[-1] if status != 'D' else None))
        offset += size
    return rows


def impact(manifests, changed_owners):
    names = {}
    for row in manifests:
        names.setdefault(row['name'], set()).add(row['owner'])
    reverse = {row['owner']: set() for row in manifests}
    for consumer in manifests:
        for dependency in consumer.get('workspace_dependencies', []):
            for provider in names.get(dependency['name'], ()):
                reverse[provider].add(consumer['owner'])
    reached = set(changed_owners)
    pending = deque(sorted(reached))
    parents = {}
    while pending:
        provider = pending.popleft()
        for consumer in sorted(reverse.get(provider, ())):
            if consumer not in reached:
                reached.add(consumer)
                parents[consumer] = provider
                pending.append(consumer)
    return dict(direct=sorted(changed_owners), transitive=sorted(reached - set(changed_owners)),
                first_dependency_parent=parents)


def observe(repository, inventory_path, base_ref, target_ref):
    repository = Path(repository).resolve()
    inventory_path = Path(inventory_path).resolve()
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes.decode('utf-8'))
    before = source_state(repository)
    if before['status'] or before['head'] != inventory['target_upstream']:
        raise ValueError('Observation requires the clean pinned source checkout')
    manifests = []
    names = {row['name'] for row in inventory['manifests'] if row.get('name')}
    seen = set()
    for row in inventory['manifests']:
        relative_manifest = PurePosixPath(row['path'])
        if relative_manifest.parts[0] != 'reference' or '..' in relative_manifest.parts:
            raise ValueError('Manifest is outside the pinned reference inventory')
        relative_manifest = relative_manifest.relative_to('reference').as_posix()
        relative_owner = PurePosixPath(row['owner']).relative_to('reference').as_posix()
        if relative_owner != str(PurePosixPath(relative_manifest).parent):
            raise ValueError('Manifest owner differs from its package directory')
        if relative_manifest in seen:
            raise ValueError('Pinned manifest is duplicated')
        seen.add(relative_manifest)
        manifest_bytes = (repository / relative_manifest).read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != row['sha256']:
            raise ValueError('Pinned manifest bytes changed: ' + relative_manifest)
        manifest = json.loads(manifest_bytes.decode('utf-8'))
        dependencies = [dict(name=name, kind=kind, version=version)
            for kind in ('dependencies', 'peerDependencies', 'optionalDependencies', 'devDependencies')
            for name, version in sorted(manifest.get(kind, {}).items()) if name in names]
        if manifest.get('name') != row['name'] or dependencies != row.get('workspace_dependencies', []):
            raise ValueError('Pinned manifest name or dependency inventory differs')
        manifests.append(dict(row, relative_manifest=relative_manifest, relative_owner=relative_owner))
    tracked_manifests = {path.decode('utf-8', 'surrogateescape') for path in
        git(repository, 'ls-files', '-z', '--', '*package.json').split(b'\0') if path}
    if seen != tracked_manifests:
        raise ValueError('Pinned manifest inventory is incomplete')
    base, target = revision(repository, base_ref), revision(repository, target_ref)
    rows = changes(repository, base, target)
    changed_owners = set()
    unmapped = []
    non_package_impact = []
    for row in rows:
        owners = []
        for path in (row['before'], row['after']):
            if path is None:
                continue
            owner = path_owner(path, manifests)
            if owner is None:
                unmapped.append(path)
            elif owner['owner'] not in owners:
                owners.append(owner['owner'])
                changed_owners.add(owner['owner'])
        row['pinned_package_owners'] = owners
        surfaces = []
        for surface in inventory.get('non_package_surfaces', []):
            relative = PurePosixPath(surface['path']).relative_to('reference').as_posix()
            if any(path is not None and (path == relative or path.startswith(relative + '/'))
                    for path in (row['before'], row['after'])):
                surfaces.append(dict(path=surface['path'], owner=surface['owner']))
        if surfaces:
            non_package_impact.append(dict(before=row['before'], after=row['after'], surfaces=surfaces))
    after = source_state(repository)
    if before != after or inventory_path.read_bytes() != inventory_bytes:
        raise ValueError('Source or inventory changed during the read-only observation')
    return dict(schema_version=1, result='observed', source_pin=inventory['target_upstream'],
        base_commit=base, target_commit=target, unchanged_checkout=before['head'],
        inventory_sha256=hashlib.sha256(inventory_bytes).hexdigest(), changes=rows,
        unmapped_paths=sorted(set(unmapped)), package_impact=impact(manifests, changed_owners),
        non_package_impact=non_package_impact,
        scope='Read-only Git delta and nearest pinned manifest/reverse declared workspace dependencies. '
              'No checkout, fetch, pin/task transition or parity acceptance. New, moved, dynamic and non-package '
              'responsibilities require source review; this package impact is advisory, not a complete runtime graph.')


def write_report(report, output, root=ROOT):
    output = Path(output).resolve()
    for protected in (root / 'reference', root / 'migration', root / '.git'):
        try:
            output.relative_to(protected.resolve())
        except ValueError:
            continue
        raise ValueError('Observation output cannot change source, Git or migration records')
    with output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, ensure_ascii=True, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description='Observe an upstream Git delta without changing the pinned checkout.')
    parser.add_argument('--base', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--output', type=Path)
    options = parser.parse_args()
    report = observe(ROOT / 'reference', ROOT / 'migration/modules.json', options.base, options.target)
    serialized = json.dumps(report, ensure_ascii=True, indent=2) + '\n'
    if options.output:
        write_report(report, options.output)
    else:
        print(serialized, end='')


if __name__ == '__main__':
    main()
