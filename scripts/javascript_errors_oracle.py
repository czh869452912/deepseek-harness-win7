import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_context_oracle import SOURCE_COMMIT, source_pin, validate_executable
from scripts.canonical_llm_oracle import SOURCE_INPUTS as CANONICAL_SOURCE_INPUTS
from scripts.canonical_llm_values import observation_digest as canonical_value_digest
from scripts.javascript_workflow_oracle import PRIVATE_ASSET_PATHS

GROUPS = ('session', 'errors')
FIXTURE_PATH = 'scripts/oracles/js-error-fixtures.json'
NAMES_BY_GROUP = json.loads((ROOT / FIXTURE_PATH).read_text(encoding='utf-8'))['names']
NAMES = tuple(group + '/' + name for group in GROUPS for name in NAMES_BY_GROUP[group])
GROUP_MODULES = {'session': ['dsh/__init__.py', 'dsh/cordis/__init__.py', 'dsh/cordis/awaiting.py', 'dsh/cordis/context.py', 'dsh/cordis/environment.py', 'dsh/cordis/errors.py', 'dsh/cordis/events.py', 'dsh/cordis/fiber.py', 'dsh/cordis/hmr.py', 'dsh/cordis/include.py', 'dsh/cordis/loader.py', 'dsh/cordis/logger.py', 'dsh/cordis/plugin.py', 'dsh/cordis/profile.py', 'dsh/cordis/reflect.py', 'dsh/cordis/registry.py', 'dsh/cordis/schema.py', 'dsh/cordis/service.py', 'dsh/cordis/timer.py', 'dsh/cordis/utils.py', 'dsh/javascript/__init__.py', 'dsh/javascript/runtime.py'], 'errors': ['dsh/__init__.py', 'dsh/cordis/__init__.py', 'dsh/cordis/awaiting.py', 'dsh/cordis/context.py', 'dsh/cordis/environment.py', 'dsh/cordis/errors.py', 'dsh/cordis/events.py', 'dsh/cordis/fiber.py', 'dsh/cordis/hmr.py', 'dsh/cordis/include.py', 'dsh/cordis/loader.py', 'dsh/cordis/logger.py', 'dsh/cordis/plugin.py', 'dsh/cordis/profile.py', 'dsh/cordis/reflect.py', 'dsh/cordis/registry.py', 'dsh/cordis/schema.py', 'dsh/cordis/service.py', 'dsh/cordis/timer.py', 'dsh/cordis/utils.py', 'dsh/javascript/__init__.py', 'dsh/javascript/runtime.py']}

SOURCE_INPUTS = {'reference/packages/core/tools/src/json-schema.ts', 'reference/vendor/cordis/src/context.ts', 'reference/vendor/cordis/src/registry.ts', 'reference/vendor/cordis/src/service.ts', 'reference/packages/workflow/workflow-worker-thread/src/runtime.ts', 'reference/packages/workflow/workflow-worker-thread/src/realm.ts', 'reference/vendor/cordis/src/utils.ts', 'reference/vendor/cordis/LICENSE', 'reference/packages/llm/llm/src/never.ts', 'reference/packages/core/session/src/types.ts', 'reference/vendor/cosmokit/src/array.ts', 'reference/vendor/cordis/src/fiber.ts', 'reference/vendor/cordis/src/reflect.ts', 'reference/LICENSE', 'reference/vendor/cosmokit/src/index.ts', 'reference/packages/workflow/workflow-worker-thread/src/protocol.ts', 'reference/vendor/cosmokit/src/string.ts', 'reference/packages/core/session/src/json.ts', 'reference/vendor/cordis/src/logger.ts', 'reference/packages/workflow/workflow-worker-thread/src/session.ts', 'reference/vendor/cosmokit/src/time.ts', 'reference/packages/workflow/workflow/src/index.ts', 'scripts/oracles/javascript_errors_observer.py', 'scripts/oracles/javascript_errors_errors.probe.spec.ts', 'reference/tsconfig.base.json', 'scripts/oracles/javascript_errors_session_python.py', 'scripts/canonical_llm_values.py', 'scripts/oracles/javascript_errors_errors_python.py', 'scripts/oracles/javascript_errors_python.py', 'reference/vendor/cosmokit/src/misc.ts', 'reference/vendor/cosmokit/src/types.ts', 'scripts/javascript_errors_oracle.py', 'scripts/oracles/javascript_errors_session.probe.spec.ts', 'reference/vendor/cordis/src/events.ts', 'scripts/oracles/vitest.javascript-errors-probe.config.mts', 'reference/vendor/cordis/src/index.ts', 'reference/packages/workflow/workflow/src/types.ts', 'scripts/runtime_context_oracle.py', 'scripts/oracles/js-error-fixtures.json', 'reference/vendor/cosmokit/LICENSE', 'scripts/javascript_workflow_oracle.py', 'reference/packages/llm/llm/src/error.ts'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation_digest(rows, side='native'):
    if not isinstance(rows, list) or len(rows) != len(NAMES) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('JavaScript errors complete rows missing')
    if tuple(row.get('name') for row in rows) != NAMES or any(row.get('group') != row['name'].split('/')[0] for row in rows):
        raise ValueError('JavaScript errors row identity or order differs')
    return canonical_value_digest(normalize_platform_observations(rows, side), side=side)


def normalize_platform_observations(rows, side):
    if side not in ('source', 'native'):
        raise ValueError('JavaScript error observation side invalid')
    fixture = json.loads((ROOT / FIXTURE_PATH).read_text(encoding='utf-8'))
    normalized = copy.deepcopy(rows)
    for row in normalized:
        group, name = row['name'].split('/', 1)
        scenario = next(item for item in fixture[group] if item['name'] == name)
        if row.get('body') != scenario['body']:
            raise ValueError('JavaScript error observed script differs')
        policy = fixture[group+'NativeDiagnostics'].get(name)
        if policy is not None:
            errors = (row['result'], row['events'][0]['result'])
            for result in errors:
                error = result.get('error')
                if not isinstance(error, str):
                    raise ValueError('JavaScript error raw diagnostic missing')
                if side == 'native' and error != policy['nativeError']:
                    raise ValueError('JavaScript error authentic native diagnostic differs')
                if side == 'source' and error.splitlines()[0] != policy['sourceFirstLine']:
                    raise ValueError('JavaScript error Source business diagnostic differs')
                result['error'] = dict(platform='native engine diagnostic', sourceFirstLine=policy['sourceFirstLine'])
        if name == 'guest-stack-properties':
            for value in (row['result']['value'],row['events'][0]['result']['value']):
                if value != fixture['stackOwnership'][side]:
                    raise ValueError('JavaScript native stack ownership differs')
                value.clear()
                value.update(dict(platform='native stack descriptor ownership'))
    return normalized


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('JavaScript errors Source identity differs')
    if not isinstance(source.get('inputs'), dict) or set(source['inputs']) != SOURCE_INPUTS:
        raise ValueError('JavaScript errors Source guard inputs differ')
    if any(not isinstance(value, str) or len(value) != 64 or any(character not in '0123456789abcdef' for character in value) for value in source['inputs'].values()):
        raise ValueError('JavaScript errors Source input hash shape differs')
    if check_files and source['inputs'] != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('JavaScript errors Source bytes changed')
    return observation_digest(source['rows'], side='source')


def validate_modules(modules, root, required, check_files):
    if not isinstance(modules, dict) or set(modules) != set(required):
        raise ValueError('JavaScript errors actual import closure differs')
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('JavaScript errors imported path invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('JavaScript errors imported identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('JavaScript errors actual imported bytes differ')


def validate_runtime(report, root, expected_digest, modules, assets=None, check_files=True):
    root = Path(root).resolve()
    if Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('JavaScript errors selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if report.get('modules') != modules:
        raise ValueError('JavaScript errors imported bytes differ')
    validate_modules(modules, root, set().union(*GROUP_MODULES.values()), check_files)
    groups = report.get('groups')
    if not isinstance(groups, dict) or set(groups) != set(GROUPS):
        raise ValueError('JavaScript errors child groups missing')
    child_rows, child_modules = [], {}
    for group in GROUPS:
        child = groups[group]
        if Path(child['root']).resolve() != root or child.get('executable') != report['executable'] or child.get('python') != report['python']:
            raise ValueError('JavaScript errors child runtime differs')
        if not isinstance(child.get('rows'), list) or tuple(row.get('name') for row in child['rows'] if isinstance(row, dict)) != tuple(NAMES_BY_GROUP[group]):
            raise ValueError('JavaScript errors child rows incomplete')
        validate_modules(child.get('modules'), root, GROUP_MODULES[group], check_files)
        for name, expected in child['modules'].items():
            if name in child_modules and child_modules[name] != expected:
                raise ValueError('JavaScript errors children disagree on bytes')
            child_modules[name] = expected
        child_rows.extend(dict(row, group=group, name=group + '/' + row['name']) for row in child['rows'])
    if child_modules != modules or child_rows != report['rows'] or observation_digest(report['rows']) != expected_digest:
        raise ValueError('JavaScript errors complete observations or child aggregate differ')

    actual_assets = report.get('assets')
    if not isinstance(actual_assets, dict) or set(actual_assets) != PRIVATE_ASSET_PATHS:
        raise ValueError('JavaScript private assets missing')
    if assets is None and not check_files:
        raise ValueError('Approved JavaScript private assets required for extracted validation')
    if assets is not None and actual_assets != assets:
        raise ValueError('JavaScript approved private assets differ')
    for group in GROUPS:
        if report['groups'][group].get('assets') != actual_assets:
            raise ValueError('JavaScript child private assets differ')
    for name, expected in actual_assets.items():
        if not name.startswith(('dsh/javascript/bin/', 'dsh/javascript/workflow/')) or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('JavaScript private asset path invalid')
        if not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('JavaScript private asset hash shape invalid')
        if check_files and digest(root / name) != expected:
            raise ValueError('JavaScript private asset bytes differ')
    if check_files:
        actual_assets = {path.relative_to(root).as_posix():digest(path) for folder in ('dsh/javascript/bin','dsh/javascript/workflow') for path in (root / folder).iterdir() if path.is_file()}
        if report['assets'] != actual_assets:
            raise ValueError('JavaScript private asset inventory differs')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh JavaScript errors outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        inputs = {name: digest(ROOT / name) for name in SOURCE_INPUTS}
        environment = dict(os.environ)
        for group in GROUPS:
            environment['DSH_JS_ERRORS_' + group.upper() + '_OUTPUT'] = str(output.with_suffix('.' + group + '.source.json'))
        completed = subprocess.run(['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run',
            '--config', 'scripts/oracles/vitest.javascript-errors-probe.config.mts'], cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
        output.with_suffix('.source.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError('Actual JavaScript errors Source observer failed')
        rows = []
        for group in GROUPS:
            child = json.loads(output.with_suffix('.' + group + '.source.json').read_text(encoding='utf-8'))
            if child['sourceCommit'] != SOURCE_COMMIT or child['node'] != 'v22.22.2' or [row['name'] for row in child['rows']] != NAMES_BY_GROUP[group]:
                raise ValueError('Actual JavaScript errors Source child identity or rows differ')
            rows.extend(dict(row, group=group, name=group + '/' + row['name']) for row in child['rows'])
        source = dict(sourceCommit=SOURCE_COMMIT, node='v22.22.2', inputs=inputs, rows=rows)
        with source_path.open('x', encoding='utf-8') as stream:
            json.dump(source, stream, indent=2)
            stream.write('\n')
        expected = identity(source)
        completed = subprocess.run([sys.executable, '-I', 'scripts/oracles/javascript_errors_python.py',
            '--root', str(ROOT), '--output', str(native_path)], cwd=str(ROOT), capture_output=True, timeout=180)
        output.with_suffix('.native.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode or completed.stderr:
            raise RuntimeError('Actual JavaScript errors native observer failed')
        native = json.loads(native_path.read_text(encoding='utf-8'))
        validate_runtime(native, ROOT, expected, native['modules'], native['assets'])
        report = dict(status='matched', cases=len(NAMES), observationsSha256=expected)
    except Exception as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
