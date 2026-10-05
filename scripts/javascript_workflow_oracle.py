import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_context_oracle import validate_executable
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
CASES = ROOT / 'tests/fixtures/javascript-workflow/cases.json'
NAMES = tuple(row['name'] for row in json.loads(CASES.read_text(encoding='utf-8')))
REQUIRED_MODULES = {'dsh/javascript/runtime.py', 'dsh/workflow/javascript_run.py',
                    'dsh/workflow/workflow_service.py', 'dsh/subagent/runtime.py', 'dsh/cordis/context.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(source):
    if source.get('sourceCommit') != SOURCE_COMMIT or not source.get('inputs'):
        raise ValueError('JavaScript workflow Source identity differs')
    required = {'reference/packages/workflow/workflow-worker-thread/src/' + name + '.ts'
                for name in ('host', 'runtime', 'realm', 'session')}
    if not required.issubset(source['inputs']):
        raise ValueError('JavaScript workflow Source input closure differs')
    return observation_digest(source['observations'])


def observation_digest(observations):
    if tuple(row['name'] for row in observations) != NAMES:
        raise ValueError('JavaScript workflow Source observations are missing, duplicate or reordered')
    return hashlib.sha256(json.dumps(observations, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def assets(root):
    return {path.relative_to(root).as_posix(): digest(path)
            for directory in ('dsh/javascript/bin', 'dsh/javascript/workflow')
            for path in sorted((root / directory).iterdir()) if path.is_file()}


def validate_runtime(report, root, expected_digest, modules, expected_assets, check_files=True):
    root = root.resolve()
    if Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('JavaScript workflow runtime root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if not REQUIRED_MODULES.issubset(report['modules']) or report['modules'] != modules:
        raise ValueError('JavaScript workflow imported module closure differs')
    for name, expected in modules.items():
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or check_files and digest(path) != expected:
            raise ValueError('JavaScript workflow imported module bytes differ')
    if report['assets'] != expected_assets or check_files and assets(root) != expected_assets:
        raise ValueError('JavaScript workflow private asset closure differs')
    if observation_digest(report['observations']) != expected_digest:
        raise ValueError('JavaScript workflow actual observations differ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error')
    try:
        source_directory = output.with_suffix('.source-workspace')
        source_path = output.with_suffix('.source.json')
        native_path = output.with_suffix('.native.json')
        commands = [
            ['node', 'scripts/oracles/javascript_workflow_host_source.mjs', str(source_directory)],
            [sys.executable, '-I', 'scripts/oracles/javascript_workflow_python.py', '--root', str(ROOT),
             '--cases', str(CASES), '--output', str(native_path)],
        ]
        for index, command in enumerate(commands):
            completed = subprocess.run(command, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
            output.with_suffix('.%d.log' % index).write_bytes(completed.stdout + completed.stderr)
            if completed.returncode or completed.stderr:
                raise RuntimeError('JavaScript workflow observer failed: ' + str(index))
        source_path.write_bytes((source_directory / 'source.json').read_bytes())
        source = json.loads(source_path.read_text(encoding='utf-8'))
        for name, expected in source['inputs'].items():
            if digest(ROOT / name) != expected:
                raise ValueError('JavaScript workflow Source input changed')
        source_digest = identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules = {name: digest(ROOT / name) for name in native['modules']}
        expected_assets = assets(ROOT)
        validate_runtime(native, ROOT, source_digest, modules, expected_assets)
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
                      observations_sha256=source_digest, modules=modules, assets=expected_assets,
                      scope='Thirty-four actual unchanged Source WorkerRun/session/runtime/schema and canonical native engine observations, including controlled physical exit before/after publication, after first result and after cancellation. Engine-specific raw errors, arbitrary Node APIs, all workflow consumers and real Win7 remain unqualified.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
