"""Read-only, version-independent upstream candidate discovery (never acceptance)."""
import argparse
import ast
from collections import Counter, deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(repository, *args):
    from scripts.upstream_delta import git as readonly_git
    return readonly_git(repository, *args)


def tree(repository, revision):
    paths = [path for path in git(repository, 'ls-tree', '-r', '--name-only', '-z', revision).decode('utf-8').split('\0') if path]
    # Read Git blobs, not checkout-normalized CRLF or an ignored build output.
    return paths


def blobs(repository, revision, paths):
    # Batch stdin avoids process-per-file overhead. Refs are resolved SHA values
    # and every path comes from ls-tree, never shell text.
    import os
    if any('\n' in path or '\r' in path for path in paths):
        raise ValueError('Candidate blob path contains a line separator')
    result = subprocess.run(['git', '--no-optional-locks', '-C', str(repository), 'cat-file', '--batch'],
        input=b''.join((revision + ':' + path).encode('utf-8') + b'\n' for path in paths),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, GIT_OPTIONAL_LOCKS='0'), check=False)
    if result.returncode:
        raise ValueError('Candidate Git blob read failed: ' + result.stderr.decode('utf-8', 'replace'))
    content, offset, rows = result.stdout, 0, {}
    for path in paths:
        # cat-file's line protocol cannot represent a newline in a requested path.
        # Refuse it rather than accidentally identifying a different blob.
        end = content.find(b'\n', offset)
        header = content[offset:end].split()
        if end < 0 or len(header) != 3 or header[1] != b'blob':
            raise ValueError('Candidate Git object is not an ordinary blob: ' + path)
        size = int(header[2])
        offset = end + 1
        rows[path] = content[offset:offset + size]
        if len(rows[path]) != size or content[offset + size:offset + size + 1] != b'\n':
            raise ValueError('Candidate Git object stream is truncated')
        offset += size + 1
    if offset != len(content):
        raise ValueError('Candidate Git object stream has trailing bytes')
    return rows


def target_profiles(text):
    """Admit only the literal profile-template grammar used by the upstream API."""
    start = re.search(r'export const PROFILE_TEMPLATES:[^=]+?=\s*\{\n', text)
    if start is None:
        return {}, 'profile template export absent; roots require explicit review'
    end = text.find('\n}', start.end())
    if end < 0:
        raise ValueError('Unterminated candidate profile templates')
    body = text[start.end():end]
    pattern = re.compile(r"\s*(?:'([^']+)'|([\w-]+)):\s*\{\s*bundles:\s*\[([^\]]*)\],?(?:\s*patchReload:\s*'(startup|live)',?)?\s*\},?")
    profiles, offset = {}, 0
    while offset < len(body):
        if not body[offset:].strip():
            break
        match = pattern.match(body, offset)
        if match is None:
            raise ValueError('Nonliteral candidate profile templates require source review')
        entries = re.findall(r"'([^']+)'", match.group(3))
        if re.sub(r"'[^']+'|[\s,]", '', match.group(3)) or not entries:
            raise ValueError('Nonliteral candidate bundle roots require source review')
        name = match.group(1) or match.group(2)
        if name in profiles:
            raise ValueError('Duplicate candidate profile template')
        profiles[name] = dict(roots=entries)
        if match.group(4) is not None:
            profiles[name]['patchReload'] = match.group(4)
        offset = match.end()
    return profiles, 'literal target templates; conditions and runtime activation are not evaluated'


PROFILE_TEMPLATE_PATHS = ('packages/boot/app-boot/src/profile.ts',
                          'packages/util/official-bundles/src/bundles.ts')


def discover_profiles(raw):
    """Follow the known official-bundles move, refusing missing or ambiguous roots."""
    declarations = []
    for path in PROFILE_TEMPLATE_PATHS:
        if path not in raw:
            continue
        text = raw[path].decode('utf-8')
        if re.search(r'export const PROFILE_TEMPLATES\s*:', text):
            profiles, scope = target_profiles(text)
            if not profiles:
                raise ValueError('Empty candidate profile templates require source review')
            declarations.append((profiles, scope, dict(path=path, sha256=hashlib.sha256(raw[path]).hexdigest())))
    if len(declarations) > 1:
        raise ValueError('Ambiguous candidate profile template sources require source review')
    app = raw.get(PROFILE_TEMPLATE_PATHS[0], b'').decode('utf-8')
    moved = re.search(r"import\s*\{[^}]*\bPROFILE_TEMPLATES\b[^}]*\}\s*from\s*'@deepseek-ai/dsh-official-bundles'", app)
    if moved:
        index = raw.get('packages/util/official-bundles/src/index.ts', b'').decode('utf-8')
        if not re.search(r"export\s*\{[^}]*\bPROFILE_TEMPLATES\b[^}]*\}\s*from\s*'\./bundles.ts'", index):
            raise ValueError('Candidate official profile re-export requires source review')
        if not declarations or declarations[0][2]['path'] != PROFILE_TEMPLATE_PATHS[1]:
            raise ValueError('Candidate official profile templates are missing')
    elif declarations and declarations[0][2]['path'] == PROFILE_TEMPLATE_PATHS[1]:
        raise ValueError('Candidate official profile consumer requires source review')
    if not declarations:
        raise ValueError('Candidate profile templates absent; roots require source review')
    return declarations[0]


def release_lanes(path):
    """Read the actual lane tuples without importing or executing release code."""
    selected = {}

    def literal(node):
        if isinstance(node, ast.Name):
            return selected[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return literal(node.left) + literal(node.right)
        return ast.literal_eval(node)

    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('PAIRED_DRIVERS', 'OFFICIAL_CONFIGS'):
                selected[name] = literal(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id in selected:
            if not isinstance(node.op, ast.Add):
                raise ValueError('Unsupported release lane assignment')
            selected[node.target.id] += literal(node.value)
    if set(selected) != {'PAIRED_DRIVERS', 'OFFICIAL_CONFIGS'}:
        raise ValueError('Release lane declarations are incomplete')
    return {key: list(value) for key, value in selected.items()}


def lane_audit(product_root, lanes, target_paths):
    """Flag source inputs for contract review, never silently rewrite old pins."""
    import fnmatch

    def matches(path, pattern):
        if pattern.endswith('/'):
            return path.startswith(pattern)
        parts, wanted = path.split('/'), pattern.split('/')

        def descend(i, j):
            if j == len(wanted):
                return i == len(parts)
            if wanted[j] == '**':
                return descend(i, j + 1) or i < len(parts) and descend(i + 1, j)
            return i < len(parts) and fnmatch.fnmatchcase(parts[i], wanted[j]) and descend(i + 1, j + 1)
        return descend(0, 0)

    result = {}
    target_paths = set(target_paths)
    for kind, names in lanes.items():
        result[kind] = []
        for name in names:
            path = ('scripts/oracles/vitest.' + name + '.config.mts' if kind == 'OFFICIAL_CONFIGS'
                    else 'scripts/' + name + '_oracle.py')
            selected = product_root / path
            if not selected.is_file():
                raise ValueError('Declared release lane is missing: ' + path)
            raw = selected.read_bytes()
            text = raw.decode('utf-8')
            refs = sorted({match.group(2) for match in re.finditer(r"(['\"])(reference/[^'\"\r\n]+)\1", text)})
            result[kind].append(dict(name=name, path=path, sha256=hashlib.sha256(raw).hexdigest(),
                literal_pins=sorted(set(re.findall(r'\b[0-9a-f]{40}\b', text))),
                literal_source_paths=[dict(path=p, target_matches=sum(matches(t, p[len('reference/'):]) for t in target_paths)) for p in refs],
                state='contract-review-required',
                limitation='Literal driver/config file only; inherited configs, imported helpers, generated paths and behavior require contract review'))
    return result


def generate(repository, base_ref, target_ref, product_root=ROOT):
    from scripts.upstream_delta import revision, source_state, parse_changes, path_owner, impact
    from scripts.migration_inventory import classification
    from dsh.boot.plugin_registry import HARNESS_PLUGIN_CLASSES
    repository, product_root = Path(repository).resolve(), Path(product_root).resolve()
    before = source_state(repository)
    base, target = revision(repository, base_ref), revision(repository, target_ref)
    paths = tree(repository, target)
    old_paths = tree(repository, base)
    selected = [p for p in paths if PurePosixPath(p).name == 'package.json' or p.endswith(('/cordis.patch.yml', '/agent.cordis.yml'))]
    for template in PROFILE_TEMPLATE_PATHS + ('packages/util/official-bundles/src/index.ts',):
        if template in paths:
            selected.append(template)
    raw = blobs(repository, target, selected)
    old = blobs(repository, base, [p for p in old_paths if PurePosixPath(p).name == 'package.json'])
    manifests = []
    for path in selected:
        if PurePosixPath(path).name != 'package.json':
            continue
        body = json.loads(raw[path].decode('utf-8'))
        role, responsibility = classification('reference/' + path)
        owner = str(PurePosixPath(path).parent)
        manifests.append(dict(path=path, owner=owner, relative_manifest=path, relative_owner=owner,
            name=body.get('name'), sha256=hashlib.sha256(raw[path]).hexdigest(),
            classification=role, responsibility=responsibility, body=body))
    # Newer bundles declare ordered patch arrays, including preset overlays.
    # Inventory every declared file rather than assuming cordis.patch.yml.
    extra_patches = set()
    for row in manifests:
        bundle = row['body'].get('dsh', {}).get('bundle')
        row['declared_bundle_patches'] = []
        if bundle is None:
            continue
        if not isinstance(bundle, dict):
            raise ValueError('Candidate bundle declaration requires source review: ' + row['path'])
        patches = bundle.get('patch')
        patches = [patches] if isinstance(patches, str) else patches
        if not isinstance(patches, list) or not patches or any(not isinstance(p, str) or not p for p in patches):
            raise ValueError('Candidate bundle patches must be literal paths: ' + row['path'])
        for patch in patches:
            part = PurePosixPath(patch)
            if part.is_absolute() or '..' in part.parts or '\\' in patch or ':' in patch:
                raise ValueError('Candidate bundle patch escapes package: ' + patch)
            path = str(PurePosixPath(row['owner']) / part)
            if path not in paths:
                raise ValueError('Candidate bundle patch is missing: ' + path)
            row['declared_bundle_patches'].append(path)
            if path not in raw:
                extra_patches.add(path)
    raw.update(blobs(repository, target, sorted(extra_patches)))
    selected.extend(sorted(extra_patches))
    declared_patches = {p for row in manifests for p in row['declared_bundle_patches']}
    by_name = {}
    for row in manifests:
        if row['name']:
            by_name.setdefault(row['name'], []).append(row)
    # Duplicate fixture names remain inventory identities, never a guessed provider.
    def package_name(name):
        return next((key for key in sorted(by_name, key=len, reverse=True) if name == key or name.startswith(key + '/')), name)

    declarations = {}
    for path in selected:
        if path not in declared_patches and not path.endswith(('/cordis.patch.yml', '/agent.cordis.yml')):
            continue
        owner = path_owner(path, manifests)
        text = raw[path].decode('utf-8')
        declarations[path] = dict(owner=owner['owner'] if owner else None,
            sha256=hashlib.sha256(raw[path]).hexdigest(),
            entries=[dict(name=m.group(2), package=package_name(m.group(2)), line=text.count('\n', 0, m.start()) + 1)
                for m in re.finditer(r"\bname:\s*(['\"])(@[^'\"]+)\1", text)],
            conditions=[dict(line=i+1, expression=line.strip()) for i, line in enumerate(text.splitlines())
                if 'disabled:' in line or '!!js' in line],
            scope='literal declarations only; disabled, isolate, inject and JS activation require runtime evidence')
    for row in manifests:
        body = row.pop('body')
        row['workspace_dependencies'] = [dict(name=name, kind=kind, version=version)
            for kind in ('dependencies', 'peerDependencies', 'optionalDependencies', 'devDependencies')
            for name, version in sorted(body.get(kind, {}).items()) if name in by_name]

    profiles, profile_scope, profile_source = discover_profiles(raw)
    for profile in profiles.values():
        pending, reached = deque(profile['roots']), set()
        while pending:
            name = package_name(pending.popleft())
            if name in reached:
                continue
            reached.add(name)
            for row in by_name.get(name, []):
                pending.extend(dep['name'] for dep in row['workspace_dependencies'] if dep['kind'] != 'devDependencies')
                patches = row['declared_bundle_patches'] or [str(PurePosixPath(row['owner']) / 'cordis.patch.yml')]
                for patch in patches:
                    if patch in declarations:
                        pending.extend(entry['package'] for entry in declarations[patch]['entries'])
        profile['potential_dependency_closure'] = sorted(reached)
        profile['scope'] = 'literal bundle rows plus non-dev workspace dependencies; never observed activation'
    changes = parse_changes(git(repository, '-c', 'diff.renameLimit=10000', 'diff', '--no-ext-diff', '--no-textconv',
        '--name-status', '-z', '--find-renames', base, target, '--'))
    owners = set()
    for change in changes:
        change['target_owners'] = []
        for path in (change['before'], change['after']):
            owner = path_owner(path, manifests) if path else None
            if owner and owner['owner'] not in change['target_owners']:
                change['target_owners'].append(owner['owner'])
                owners.add(owner['owner'])
    for row in manifests:
        row['change'] = 'added' if row['path'] not in old else 'changed' if row['owner'] in owners else 'unchanged'
        row['python_loader_entrypoints'] = {key: value for key, value in HARNESS_PLUGIN_CLASSES.items()
            if key == row['name'] or row['name'] and key.startswith(row['name'] + '/')}
        row['potential_profiles'] = [key for key, profile in profiles.items() if row['name'] in profile['potential_dependency_closure']]
        row['parity'] = 'not-certified-by-inventory'
        row.pop('relative_manifest')
        row.pop('relative_owner')
    # Runtime-only reverse graph: devDependencies are inventoried but cannot
    # promote a test/tooling edge into a shipped runtime dependency.
    runtime = [dict(row, workspace_dependencies=[d for d in row['workspace_dependencies'] if d['kind'] != 'devDependencies']) for row in manifests]
    graph = impact(runtime, owners)
    lanes_path = product_root / 'scripts/verify_release.py'
    lanes = release_lanes(lanes_path) if lanes_path.is_file() else {}
    after = source_state(repository)
    if before != after:
        raise ValueError('Source changed during candidate discovery')
    return dict(schema_version=1, state='candidate-discovery', base_upstream=base, target_upstream=target,
        unchanged_checkout=before['head'], checkout_dirty=bool(before['status']),
        scope='Git-object discovery only; active pin/tasks and runtime activation are unchanged',
        counts=dict(manifests=len(manifests), classifications=dict(Counter(r['classification'] for r in manifests)),
            changes=len(changes), statuses=dict(Counter(r['status'][0] for r in changes))),
        profiles=profiles, profile_scope=profile_scope, profile_template_source=profile_source, declarations=declarations,
        manifests=sorted(manifests, key=lambda r: r['path']),
        removed_manifests=[dict(path=p, name=json.loads(v.decode('utf-8')).get('name')) for p, v in sorted(old.items()) if p not in paths],
        runtime_dependency_impact=graph, release_lanes=lanes,
        release_lane_audit=lane_audit(product_root, lanes, paths),
        non_package_surfaces=[dict(path=p, status=r['status']) for r in changes for p in [r['after'] or r['before']]
            if not p.startswith(('packages/', 'apps/', 'vendor/'))],
        source_tests=[p for p in paths if re.search(r'\.(?:spec|test)\.[cm]?[jt]sx?$', p)],
        changes=changes)


def write_report(report, output, repository, product_root=ROOT):
    output = Path(output).resolve()
    for protected in (Path(repository).resolve(), Path(product_root).resolve() / 'reference',
                      Path(product_root).resolve() / '.git'):
        if output == protected or protected in output.parents:
            raise ValueError('Candidate output cannot change Source or Git metadata')
    # Candidate records are permitted; active migration records are not.
    migration = Path(product_root).resolve() / 'migration'
    if migration in output.parents and migration / 'candidates' not in output.parents:
        raise ValueError('Candidate output cannot change active migration records')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, default=ROOT / 'reference')
    parser.add_argument('--base', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = generate(args.repository, args.base, args.target)
    write_report(report, args.output, args.repository)
    print(json.dumps(report['counts']))


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    main()
