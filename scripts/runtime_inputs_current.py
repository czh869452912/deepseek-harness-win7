"""Current runtime data, declared overlays and retained compatibility identities."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGET = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'
HISTORY = 'migration/candidates/rc022/previous-runtime-inputs.json'
OVERLAYS = {
    'apps/cli/package.json': ('@deepseek-win7/dsh-creative', None),
    'packages/bundle/base/package.json': ('@deepseek-win7/dsh-ptc-runtime-python', './win7-runtime.patch.yml'),
    'packages/bundle/sdk-minimal/package.json': ('@deepseek-ai/dsh-tool-str-replace-editor', './win7-minimal.patch.yml'),
}
PRODUCT = {
    'packages/bundle/base/win7-runtime.patch.yml': 'Explicit installed Python PTC overlay.',
    'packages/bundle/creative/cordis.patch.yml': 'Explicit installed Python Creative manager overlay.',
    'packages/bundle/creative/package.json': 'Private Native Creative bundle installation closure.',
    'packages/bundle/sdk-minimal/win7-minimal.patch.yml': 'Explicit two-tool Win7 Minimal composition.',
    'packages/code-runtime/code-runtime-python/package.json': 'Retained optional Native Python execution provider.',
    'packages/compat/cordis-manager-python/package.json': 'Private Native seven-tool Creative manager identity.',
    'packages/compat/ptc-runtime-python/package.json': 'Private confined Python PTC identity.',
    'packages/extensions/tool-python-export/package.json': 'Retained optional Native export extension.',
    'packages/preset/agent-presets/presets/cordis/agent.cordis.yml': 'Retained Native Creative compatibility preset.',
    'packages/preset/agent-presets/presets/ptc/agent.cordis.yml': 'Retained Native PTC compatibility preset.',
    'packages/preset/agent-presets/presets/standard/agent.cordis.yml': 'Retained Native Standard compatibility preset.',
    'packages/session/session-persistence-sqlite/package.json': 'Retained optional historical SQLite persistence identity.',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def runtime_paths(root):
    paths = {root / 'apps/cli/package.json'}
    for pattern in ['packages/*/*/package.json', 'packages/*/*/lib/typert.host.js', 'packages/bundle/*/*.yml']:
        paths.update(root.glob(pattern))
    resources = root / 'packages/preset/agent-presets/presets'
    if resources.exists():
        paths.update(path for path in resources.rglob('*') if path.is_file()
                     and '__pycache__' not in path.parts and path.suffix not in ['.pyc', '.pyo'])
    return sorted(paths)


def validate(root, manifest, target):
    root = Path(root).resolve()
    if manifest.get('schema_version') != 2 or manifest.get('target_upstream') != target or target != TARGET:
        raise ValueError('Current runtime target/schema differs')
    rows = manifest.get('files', [])
    if not rows: raise ValueError('Current runtime input roster is empty')
    seen = set()
    for row in rows:
        name = row['path']; path = root / name
        if (name in seen or Path(name).is_absolute() or ':' in name or '..' in Path(name).parts or '\\' in name
                or not (name == 'apps/cli/package.json' or name.startswith('packages/'))
                or path.resolve() != path.absolute()):
            raise ValueError('Current runtime input path is duplicated, linked or outside its scope')
        seen.add(name)
        if row.get('origin') not in ['current-source', 'product-overlay', 'retained-compatibility', 'native-product']:
            raise ValueError('Unknown runtime input provenance')
        if row['origin'] in ['current-source', 'product-overlay']:
            checksum = row.get('source_sha256')
            if row.get('source_upstream') != TARGET or not isinstance(checksum, str) or not re.fullmatch('[0-9a-f]{64}', checksum):
                raise ValueError('Current Source runtime identity is incomplete')
        if sha(path) != row['sha256']:
            raise ValueError('Runtime input differs: ' + name)
    if {path.relative_to(root).as_posix() for path in runtime_paths(root)} != seen:
        raise ValueError('Current runtime resource input roster differs')


def generate(source, root=ROOT):
    if (subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip() != TARGET
            or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], encoding='utf-8').strip()):
        raise ValueError('Unchanged current Source required')
    history = json.loads((root / HISTORY).read_text(encoding='utf-8'))
    previous = {row['path']: row for row in history['files'] + history.get('native_files', [])}
    rows = []
    for path in runtime_paths(root):
        name = path.relative_to(root).as_posix(); original = source / name; checksum = sha(path)
        if original.is_file() and original.read_bytes() == path.read_bytes():
            row = dict(origin='current-source', source_upstream=TARGET, source_sha256=sha(original), product_overlay=False)
        elif name in OVERLAYS:
            expected = copy.deepcopy(json.loads(original.read_text(encoding='utf-8')))
            dependency, patch = OVERLAYS[name]
            expected['dependencies'][dependency] = 'workspace:*'
            if patch: expected['dsh']['bundle']['patch'] = ['./cordis.patch.yml', patch]
            if json.loads(path.read_text(encoding='utf-8')) != expected:
                raise ValueError('Undeclared application metadata overlay: ' + name)
            row = dict(origin='product-overlay', source_upstream=TARGET, source_sha256=sha(original), product_overlay=True)
        elif name in previous and checksum == previous[name]['sha256']:
            old = previous[name]
            row = dict(origin='retained-compatibility', source_upstream=history['target_upstream'],
                       source_sha256=old.get('source_sha256'), product_overlay=old.get('product_overlay', True),
                       previous_sha256=checksum)
        elif name in PRODUCT:
            row = dict(origin='native-product', source_upstream=None, source_sha256=None,
                       product_overlay=True, reason=PRODUCT[name])
        else:
            raise ValueError('Unreviewed runtime data: ' + name)
        rows.append(dict(path=name, sha256=checksum, **row))
    manifest = dict(schema_version=2, target_upstream=TARGET,
        scope='Shipped runtime data identities. Current Source bytes, three explicit metadata overlays, retained historical compatibility data and Native product resources are distinct; retained data is not current upstream parity.',
        previous_manifest_path=HISTORY, previous_manifest_sha256=sha(root / HISTORY), files=rows, native_files=[])
    validate(root, manifest, TARGET)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.source.resolve())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(len(result['files']))
