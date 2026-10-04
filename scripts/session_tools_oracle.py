import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODULES = ['dsh/session/tool_query.py', 'dsh/session/tool_query_input.py', 'dsh/session/tool_query_boundary.py',
           'dsh/session/tool_query_workspace.py', 'dsh/session/tool_query_presentation.py', 'dsh/session/tool_query_operations.py',
           'dsh/core/tools.py']
SCENARIOS = ['empty', 'pages', 'private-failure', 'foreign-failure', 'repeated-cursor', 'prior-events',
             'empty-step-range', 'unauthorized-before-query', 'lineage', 'relationships', 'exact-read', 'invalid-schema', 'invalid-integer']
NAMES = (['query-' + str(index) for index in range(6)] + ['timestamp-' + str(index) for index in range(14)]
         + ['range-' + str(index) for index in range(4)] + ['registration']
         + [name for scenario in SCENARIOS for name in (scenario, scenario + '-metadata')]
         + ['failure-' + str(index) for index in range(18)] + ['config-' + str(index) for index in range(6)]
         + ['abort-false', 'abort-true', 'harness-error-kind'])
INPUTS = MODULES + ['scripts/session_tools_oracle.py', 'scripts/oracles/session_tools_python.py',
                   'scripts/oracles/session_tools.probe.spec.ts', 'scripts/oracles/vitest.session-tools-probe.config.mts',
                   'scripts/oracles/vitest.session-tools-source.config.mts', 'tests/test_session_tools.py',
                   'tests/test_session_tools_source.py', 'tests/test_session_tools_profile.py', 'dsh/boot/plugin_registry.py']
INPUTS += [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'reference/packages/session-query/tool-session-query').rglob('*'))
           if path.is_file() and ('src' in path.parts or 'tests' in path.parts)]


def module_hashes(root):
    return {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() for name in MODULES}


def observation_digest(rows):
    if not isinstance(rows, list) or [row.get('name') if isinstance(row, dict) else None for row in rows] != NAMES:
        raise ValueError('Session tool observation inventory differs')
    for row in rows:
        if set(row) not in ({'name', 'value'}, {'name', 'error'}):
            raise ValueError('Session tool outcome is malformed')
        if 'error' in row and (not isinstance(row['error'], dict) or set(row['error']) != {'code', 'message'}
                or not isinstance(row['error']['message'], str)):
            raise ValueError('Session tool error is malformed')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()


def source_identity(source):
    if not isinstance(source, dict) or set(source) != {'node', 'rows'} or source['node'] != 'v22.22.2':
        raise ValueError('Pinned Session tool source runtime differs')
    return observation_digest(source['rows'])


def validate_runtime(report, root=None, expected_digest=None, expected_modules=None):
    if not isinstance(report, dict) or set(report) != {'root', 'python', 'moduleFile', 'modules', 'rows'}:
        raise ValueError('Session tool runtime receipt is incomplete')
    if not isinstance(report['root'], str):
        raise ValueError('Session tool root is malformed')
    expected_root = Path(root if root is not None else report['root']).resolve()
    if (report['root'] != str(expected_root) or report['moduleFile'] != str(expected_root / MODULES[0]) or report['python'] != '3.8.10'):
        raise ValueError('Session tool runtime provenance differs')
    modules = expected_modules if expected_modules is not None else module_hashes(expected_root)
    if (not isinstance(modules, dict) or set(modules) != set(MODULES)
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in modules.values())
            or report['modules'] != modules):
        raise ValueError('Session tool module closure differs')
    observed = observation_digest(report['rows'])
    if expected_digest is not None and (not isinstance(expected_digest, str) or not re.fullmatch('[0-9a-f]{64}', expected_digest)
                                        or observed != expected_digest):
        raise ValueError('Session tool observations differ from the actual source')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='failed')
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if target != actual or dirty:
            raise ValueError('Session tools require the clean pinned source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        source_path, native_path = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Session tools require the pinned Node runtime')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run', '--config',
                     str(ROOT / 'scripts/oracles/vitest.session-tools-probe.config.mts')],
                    [sys.executable, '-I', str(ROOT / 'scripts/oracles/session_tools_python.py'), str(native_path)]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, SESSION_TOOLS_OUTPUT=str(source_path)),
                                    capture_output=True, timeout=120)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Session tool observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        native = json.loads(native_path.read_text(encoding='utf-8'))
        expected_digest = source_identity(source)
        validate_runtime(native, ROOT, expected_digest)
        if report['inputSha256'] != hashes():
            raise ValueError('Session tool observation inputs changed')
        report.update(status='passed', cases=len(NAMES), observationsSha256=expected_digest,
                      scope='Optional five-tool registration, literal/precise inputs, controlled provider authorization, pagination, lineage, read, safe errors and abort precedence. Full plugin ABI and complete migration remain open.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
