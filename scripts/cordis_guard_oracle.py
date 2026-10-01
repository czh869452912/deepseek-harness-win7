"""Pinned Host Guard comparison, with an exact callable-service bug exception."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_INPUTS = ['scripts/oracles/cordis-guard-cases.json', 'scripts/oracles/cordis-guard.spec.ts',
    'scripts/oracles/vitest.cordis-guard-probe.config.mts', 'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts',
    'reference/packages/extensions/cordis-host-runner/src/guard.ts',
    'reference/packages/extensions/cordis-host-runner/tests/helpers.ts',
    'reference/packages/core/tools/src/schema.ts', 'reference/packages/core/tools/src/json-schema.ts']
INPUTS = SOURCE_INPUTS + ['scripts/cordis_guard_oracle.py', 'scripts/oracles/cordis_guard_python.py',
    'dsh/extensions/cordis_guard.py', 'dsh/extensions/host_runner.py', 'dsh/extensions/cordis_runner_state.py',
    'dsh/core/tools.py', 'dsh/core/json_schema.py', 'dsh/core/scope.py', 'dsh/core/session/json.py',
    'dsh/cordis/context.py', 'dsh/cordis/reflect.py', 'dsh/cordis/fiber.py', 'dsh/cordis/utils.py',
    'dsh/llm/error.py', 'tests/test_cordis_guard.py', 'tests/fixtures/cordis-guard-source-observations.json']
BUG_MODES = ('facade/callable-context', 'facade/callable-async-context')
BUG_MESSAGE = ('service "callable" returned a cordis Context, which the sandbox does not expose. '
    'Operate through your own plugin ctx (ctx.on / ctx.provide / ctx.tools.register) '
    'and the services you inject — never another context.')


def corrected_observation(source):
    if source not in [dict(mode=mode, value=dict(value=dict(escaped=True), reports=[])) for mode in BUG_MODES]:
        raise ValueError('not the reviewed callable service Context leak')
    return dict(mode=source['mode'], value=dict(error=dict(message=BUG_MESSAGE), reports=[BUG_MESSAGE]))


def classify(source, native):
    if source == native:
        return 'matched'
    try:
        if corrected_observation(source) == native:
            return 'reviewed-upstream-bug/CORDIS-GUARD-001'
    except (ValueError, KeyError, TypeError):
        pass
    return 'different'


def digests(paths, normalized=False):
    return {path: hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8') if normalized else (ROOT / path).read_bytes()).hexdigest() for path in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--refresh-source-fixture', action='store_true')
    args = parser.parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error', cases=[])
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        if subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip() != target:
            raise ValueError('reference differs from pinned target')
        if subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain', '--untracked-files=no'], encoding='utf-8').strip():
            raise ValueError('tracked reference changes')
        report['target_upstream'] = target
        modes = [spec['mode'] for spec in json.loads((ROOT / SOURCE_INPUTS[0]).read_text(encoding='utf-8'))]
        if not modes or len(set(modes)) != len(modes):
            raise ValueError('empty or duplicate observations')
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        for path in paths:
            if path.exists():
                path.unlink()
        commands = [['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.cordis-guard-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/cordis_guard_python.py', str(paths[1])]]
        env = dict(os.environ, CORDIS_GUARD_OUTPUT=str(paths[0]))
        for index, command in enumerate(commands):
            run = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError('runner %d failed (%d)' % (index, run.returncode))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        if any([row['mode'] for row in observations] != modes for observations in (source, native)):
            raise ValueError('missing, duplicate or unexpected observations')
        fixture_path = ROOT / 'tests/fixtures/cordis-guard-source-observations.json'
        if args.refresh_source_fixture:
            fixture_path.write_text(json.dumps(dict(target_upstream=target, source_sha256=digests(SOURCE_INPUTS, True), observations=source), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        fixture = json.loads(fixture_path.read_text(encoding='utf-8'))
        if fixture != dict(target_upstream=target, source_sha256=digests(SOURCE_INPUTS, True), observations=source):
            raise ValueError('source fixture/inputs differ from actual pinned observation')
        report['cases'] = [dict(mode=left['mode'], status=classify(left, right)) for left, right in zip(source, native)]
        report['status'] = 'passed' if all(row['status'] != 'different' for row in report['cases']) else 'different'
        report['input_sha256'] = digests(INPUTS)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'], {status: sum(row['status'] == status for row in report['cases']) for status in ('matched', 'reviewed-upstream-bug/CORDIS-GUARD-001', 'different')})
    return {'passed': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
