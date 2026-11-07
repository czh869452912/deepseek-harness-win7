"""Import reviewed rc.3 runtime data with verified backups and explicit product overlays."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.import_frontend import replace_bytes

TARGET = 'a4c74a91e06b00fe0b0937bde982170c526cc842'
CREATIVE_DIR = 'packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/'
CREATIVE_SKILL = CREATIVE_DIR + 'SKILL.md'
CREATIVE_ADAPTATION = 'Creative development guidance targets Python 3.8.10/Win7; native references and runnable examples are product-owned inputs.'


def validate_runtime_inputs(root, manifest, target):
    root = Path(root).resolve()
    if manifest.get('target_upstream') != target or not manifest.get('files'):
        raise ValueError('Runtime input target or roster differs')
    native = manifest.get('native_files', [])
    if any(row.get('product_owned') is not True or not row['path'].startswith(
            (CREATIVE_DIR + 'references/', CREATIVE_DIR + 'examples/')) for row in native):
        raise ValueError('Native Creative input outside the reviewed resource scope')
    seen = set()
    for row in manifest['files'] + manifest.get('native_files', []):
        name = row['path']
        path = (root / name).resolve()
        path.relative_to(root)
        if name in seen or not (name == 'apps/cli/package.json' or name.startswith('packages/')):
            raise ValueError('Runtime input path is duplicated or outside its scope')
        seen.add(name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('Runtime input differs: ' + name)
    if native:
        resources = {path.relative_to(root).as_posix() for path in (root / CREATIVE_DIR).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc', '.pyo')}
        if resources != {name for name in seen if name.startswith(CREATIVE_DIR)}:
            raise ValueError('Creative resource input roster differs')


def reviewed_creative_inputs(root, selected):
    """Keep an explicitly reviewed language overlay when reimporting this pin."""
    path = root / 'scripts/runtime-inputs.json'
    if not path.exists():
        return {}, []
    manifest = json.loads(path.read_text(encoding='utf-8'))
    skill = next((row for row in manifest.get('files', []) if row['path'] == CREATIVE_SKILL), None)
    native = manifest.get('native_files', [])
    if not skill or not skill.get('product_overlay'):
        if native:
            raise ValueError('Native Creative inputs require the reviewed skill overlay')
        return {}, []
    if (manifest.get('target_upstream') != TARGET or CREATIVE_SKILL not in selected
            or hashlib.sha256(selected[CREATIVE_SKILL]).hexdigest() != skill['source_sha256']):
        raise ValueError('Creative Source changed; review its Python overlay before importing')
    if any(not row['path'].startswith((CREATIVE_DIR + 'references/', CREATIVE_DIR + 'examples/')) for row in native):
        raise ValueError('Native Creative input outside the reviewed resource scope')
    validate_runtime_inputs(root, dict(target_upstream=TARGET, files=[skill], native_files=native), TARGET)
    return {CREATIVE_SKILL: (root / CREATIVE_SKILL).read_bytes().decode('utf-8')}, native


def selected_inputs(source):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source)] + list(args), encoding='utf-8').strip()
    if git('rev-parse', 'HEAD') != TARGET or git('status', '--porcelain'):
        raise ValueError('Unchanged pinned rc.3 Source required')
    names = git('ls-files', '-z').split('\0')
    selected = [name for name in names if name == 'apps/cli/package.json' or
                name.startswith('packages/') and (name.endswith('/package.json') or
                name.startswith('packages/bundle/') and name.endswith('/cordis.patch.yml') or
                name.startswith('packages/preset/agent-presets/presets/'))]
    selected += [path.relative_to(source).as_posix() for path in source.glob('packages/*/*/lib/typert.host.js')]
    if not any(name.endswith('/typert.host.js') for name in selected):
        raise ValueError('Built strict Typert descriptors required')
    return {name: (source / name).read_bytes() for name in sorted(set(selected))}


def import_inputs(source, root, output):
    selected = selected_inputs(source)
    creative, native_files = reviewed_creative_inputs(root, selected)
    output.resolve().relative_to((root / '.goose/out').resolve())
    output.mkdir(parents=True, exist_ok=False)
    before = {name: (root / name).read_bytes() for name in selected if (root / name).is_file()}
    minimal = 'packages/preset/agent-presets/presets/minimal/agent.cordis.yml'
    marker = '# The bare local filesystem shadows'
    old_minimal = before[minimal].decode('utf-8')
    if marker not in old_minimal:
        raise ValueError('Reviewed two-tool Minimal overlay missing')
    overlays = {minimal: selected[minimal].decode('utf-8').rstrip() + '\n\n' + old_minimal[old_minimal.index(marker):]}
    sdk = 'packages/bundle/sdk-minimal/cordis.patch.yml'
    overlays[sdk] = selected[sdk].decode('utf-8').rstrip() + '''

    # Product requirement: Minimal retains the editor alongside the persistent shell.
    - id: fs-local
      name: '@deepseek-ai/dsh-fs-local'
      config:
        cwd: !!js process.env.DSH_CWD ?? process.cwd()

    - id: str-replace-editor
      name: '@deepseek-ai/dsh-tool-str-replace-editor'
      config:
        maxOutputChars: 16000
'''
    metadata = 'packages/preset/agent-presets/presets/minimal/preset.yml'
    overlays[metadata] = 'name: 极简模式\ndescription: 持久 shell 与 str_replace_editor 的双工具编码 Agent。\norder: 3\n'
    overlays.update(creative)
    archive = output / 'previous-runtime-inputs.zip'
    with zipfile.ZipFile(str(archive), 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, content in before.items(): bundle.writestr(name, content)
    with zipfile.ZipFile(str(archive)) as bundle:
        if bundle.testzip() is not None or any(bundle.read(name) != content for name, content in before.items()):
            raise ValueError('Previous runtime input backup failed verification')
    for name, content in selected.items():
        replace_bytes(root / name, overlays[name].encode('utf-8') if name in overlays else content)
    if selected_inputs(source) != selected:
        raise ValueError('Source inputs changed during import')
    rows = [dict(path=name, source_sha256=hashlib.sha256(content).hexdigest(),
                 sha256=hashlib.sha256((root / name).read_bytes()).hexdigest(), product_overlay=name in overlays)
            for name, content in selected.items()]
    report = dict(target_upstream=TARGET, scope='Runtime manifests, bundle rows, agent presets and built strict host descriptors only; not a Source mirror or release qualification.',
                  files=rows, native_files=native_files, previous_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                  adaptations=['Win7 Minimal and SDK Minimal retain str_replace_editor with a local fs provider.']
                    + ([CREATIVE_ADAPTATION] if creative else []))
    (output / 'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    report=import_inputs(args.source.resolve(), ROOT, args.output.resolve())
    print(json.dumps(dict(target=TARGET, files=len(report['files']))))


if __name__ == '__main__': main()
