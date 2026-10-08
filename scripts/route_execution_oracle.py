"""Qualify seven canonical child routes against Source and an unchanged ZIP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.route_execution_values import project
from scripts.verify_portable import extract

PIN = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
OBSERVERS = ('scripts/route_execution_oracle.py', 'scripts/route_execution_values.py') + tuple(
    'scripts/oracles/route_execution/' + name for name in ('route_execution_native_v1.py',
    'route_execution_source_v1.mts', 'route_execution_fixture_v1.py', 'route_execution_fixture_v1.mts'))
REQUIRED = {'dsh/core/agent.py', 'dsh/core/agent_loop.py', 'dsh/core/tools.py',
    'dsh/subagent/canonical_tools.py', 'dsh/subagent/model_selection.py', 'dsh/subagent/in_process.py',
    'dsh/subagent/runtime.py', 'dsh/session/persistence_jsonl_canonical.py',
    'dsh/llm/llm_service.py', 'dsh/boot/profile_boot.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*arguments, **options):
    return subprocess.check_output(['git', '-C', str(options.get('root', ROOT))] + list(arguments),
                                   encoding='utf-8').strip()


def inputs(checkout, product=False):
    result = {}
    for entry in git('ls-files', '-s', '-z', root=checkout).split('\0'):
        if not entry:
            continue
        metadata, name = entry.split('\t', 1)
        mode, revision, stage = metadata.split(' ')
        if stage != '0':
            raise ValueError('Unmerged input: ' + name)
        if mode == '160000':
            if not product or name != 'reference' or revision != PIN:
                raise ValueError('Unexpected Source submodule identity')
        elif not product or name.startswith(('dsh/', 'apps/', 'packages/')) or name in OBSERVERS:
            result[name] = digest(checkout / name)
    return result


def runtime(report, checkout, executable, approved):
    if (report.get('root') != str(checkout) or Path(report['executable']).resolve() != executable.resolve()
            or not report['python'].startswith('3.8.10 ') or report.get('failure')
            or report.get('exitCode') != 0 or report['fixtureSha256'] != digest(ROOT / OBSERVERS[-2])):
        raise ValueError('Route runtime or fixture identity differs')
    modules = report['modules']
    if not REQUIRED.issubset(modules):
        raise ValueError('Route runtime imports incomplete')
    for name, expected in modules.items():
        if name not in approved or approved[name] != expected or digest(checkout / name) != expected:
            raise ValueError('Unapproved route runtime import: ' + name)
    return modules


def compare(source, native):
    left = project(source, source['sourceRoot'] + '\\')
    right = project(native, native['root'])
    differences = []

    def walk(a, b, path):
        if type(a) is not type(b):
            differences.append(dict(path=path, source=a, native=b))
        elif isinstance(a, dict):
            for name in sorted(set(a) | set(b)):
                if name not in a or name not in b:
                    differences.append(dict(path=path + [name], sourcePresent=name in a,
                        nativePresent=name in b, source=a.get(name), native=b.get(name)))
                else:
                    walk(a[name], b[name], path + [name])
        elif isinstance(a, list):
            if len(a) != len(b):
                differences.append(dict(path=path, sourceLength=len(a), nativeLength=len(b)))
            for index, pair in enumerate(zip(a, b)):
                walk(pair[0], pair[1], path + [index])
        elif a != b:
            differences.append(dict(path=path, source=a, native=b))

    walk(left, right, [])
    return dict(status='matched' if not differences else 'different', differences=differences,
        observationsSha256=hashlib.sha256(json.dumps(left, sort_keys=True, ensure_ascii=True,
            separators=(',', ':')).encode('utf-8')).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output, archive = args.output_dir.resolve(), args.archive.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status='failed', productCommit=git('rev-parse', 'HEAD'), sourceCommit=PIN,
        scope='Seven complete canonical selected child routes with local adapters; no paid calls. '
              'No background/completed-prefix fork, arbitrary graph ABI or whole-parent certification.')
    try:
        if git('status', '--porcelain') or git('rev-parse', 'HEAD', root=ROOT/'reference') != PIN or git('status', '--porcelain', root=ROOT/'reference'):
            raise ValueError('Clean product and pinned Source required')
        if subprocess.check_output(['node', '--version'], encoding='utf-8').strip() != 'v22.22.2':
            raise ValueError('Pinned Node22.22.2 required')
        root_inputs, source_inputs = inputs(ROOT, True), inputs(ROOT/'reference')
        report.update(rootInputs=root_inputs, sourceInputs=source_inputs,
            observerInputs={name:digest(ROOT/name) for name in OBSERVERS}, archiveSha256=digest(archive))
        extracted = Path(tempfile.mkdtemp(prefix='dsh-route-')).resolve()
        if extracted.parent != Path(tempfile.gettempdir()).resolve() or extracted.is_symlink():
            raise ValueError('Isolated extracted owner differs')
        report['extractedWorkspace'] = str(extracted)
        owned = extract(archive, extracted)
        owned_inputs = {path.relative_to(owned).as_posix():digest(path) for path in owned.rglob('*') if path.is_file()}
        provenance = json.loads((owned/'build-provenance.json').read_text(encoding='utf-8'))
        if provenance['product_commit'] != report['productCommit'] or provenance['worktree_dirty'] is not False:
            raise ValueError('Archive is not the exact clean candidate')
        report.update(ownedInputs=owned_inputs, provenance=provenance)
        environment = {name:value for name,value in os.environ.items()
            if not re.search(r'(API.?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)', name, re.I)}
        environment.update(PYTHONDONTWRITEBYTECODE='1', TSX_TSCONFIG_PATH=str(ROOT/'reference/tsconfig.json'))
        workspace = output/'workspace'
        observers = ROOT/'scripts/oracles/route_execution'

        def run(command, label):
            completed = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=180)
            (output/(label+'.log')).write_bytes(completed.stdout + completed.stderr)
            if completed.returncode or completed.stderr:
                raise ValueError('Route physical process failed or emitted stderr: ' + label)
            return json.loads((output/(label+'.json')).read_text(encoding='utf-8'))

        source = run(['node', '--import', (ROOT/'reference/node_modules/tsx/dist/loader.mjs').as_uri(),
            str(observers/'route_execution_source_v1.mts'), '--root', str(ROOT/'reference'),
            '--run-dir', str(output/'source-run'), '--workspace', str(workspace), '--output', str(output/'source.json')], 'source')
        if source['sourceCommit'] != PIN or source['node'] != 'v22.22.2' or source['fixtureSha256'] != digest(ROOT/OBSERVERS[-1]):
            raise ValueError('Route Source identity differs')
        modules = {}
        for label, checkout, executable, approved in (
                ('native', ROOT, ROOT/'.venv/Scripts/python.exe', root_inputs),
                ('owned', owned, owned/'python.exe', owned_inputs)):
            native = run([str(executable), '-I', '-B', str(observers/'route_execution_native_v1.py'),
                '--root', str(checkout), '--run-dir', str(output/(label+'-run')), '--workspace', str(workspace),
                '--port', str(source['port']), '--output', str(output/(label+'.json'))], label)
            modules[label] = runtime(native, checkout, executable, approved)
            comparison = compare(source, native)
            (output/(label+'.comparison.json')).write_text(json.dumps(comparison, indent=2)+'\n', encoding='utf-8')
            report[label+'Comparison'] = comparison
            if comparison['status'] != 'matched':
                raise ValueError('Complete route observations differ: ' + label)
        if modules['native'] != modules['owned']:
            raise ValueError('Root/ZIP actual import closure differs')
        if root_inputs != inputs(ROOT, True) or source_inputs != inputs(ROOT/'reference') or git('status', '--porcelain'):
            raise ValueError('Route guarded inputs changed')
        if report['archiveSha256'] != digest(archive) or any(digest(owned/name) != expected for name,expected in owned_inputs.items()):
            raise ValueError('Route archive/extracted bytes changed')
        actual = {path.relative_to(owned).as_posix():digest(path) for path in owned.rglob('*') if path.is_file()}
        if actual != owned_inputs or any(path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400
                for path in extracted.rglob('*')):
            raise ValueError('Unknown or aliased extracted route material')
        if {path.name for path in extracted.iterdir()} != {'dsh-win7-portable'}:
            raise ValueError('Unknown extracted route sibling')
        shutil.rmtree(str(extracted))
        report['extractedCleanup'] = dict(status='completed', path=str(extracted),
            removedFiles=len(owned_inputs), scope='Only unchanged ZIP inputs after final process exit and full late guards.')
        report.update(status='matched', cases=7, runtimeImports=modules['native'])
    except Exception as error:
        report['failure'] = dict(name=type(error).__name__, message=str(error))
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], cases=report.get('cases'), failure=report.get('failure'))))
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
