import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
NAMES = ('host-exit-contained', 'pending-host-exit', 'mixed-failure', 'single-failure')
INPUTS = ['scripts/subprocess_ownership_oracle.py', 'scripts/oracles/subprocess_ownership_python.py',
    'scripts/oracles/subprocess_ownership.probe.spec.ts', 'scripts/oracles/vitest.subprocess-ownership-probe.config.mts',
    'scripts/oracles/vitest.subagent-acp.config.mts', 'scripts/oracles/vitest.acp.config.mts',
    'scripts/oracles/official/package-lock.json', 'dsh/subprocess/local.py', 'dsh/subprocess/service.py',
    'dsh/subprocess/types.py', 'dsh/cordis/errors.py', 'tests/test_subprocess_ownership_source.py',
    'tests/test_subprocess_ownership_observer.py', 'reference/packages/subprocess/subprocess-local/src/index.ts']


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(',', ':'))


def expected():
    rows = []
    for name in NAMES:
        if name == 'host-exit-contained':
            observed = {'trace': [['force', 'ordinary'], ['force', 'terminal']],
                'after': {'ordinary': 1, 'terminals': 1}, 'retained': {'ordinary': 1, 'terminals': 1}}
        else:
            trace = [['terminate', 'ordinary']]
            if name == 'mixed-failure':
                trace += [['terminate', 'terminal']]
            trace += [['wait', 'ordinary'], ['force', 'ordinary']]
            if name == 'mixed-failure':
                trace += [['force', 'terminal']]
            observed = {'trace': trace, 'after': {'ordinary': 0, 'terminals': 0}}
            if name == 'pending-host-exit':
                observed['retained'] = {'ordinary': 1, 'terminals': 0}
            else:
                observed['error'] = {'name': 'Error', 'message': 'controlled wait failure', 'sameWaitFailure': True}
                if name == 'mixed-failure':
                    observed['error'].update(name='AggregateError', message='local subprocess teardown failed', sameWaitFailure=False,
                        members=[{'name': 'Error', 'message': 'controlled wait failure'},
                            {'name': 'Error', 'message': 'controlled terminal failure'}], memberIdentity=True)
        rows.append({'name': name, 'observed': observed})
    return rows


def validate_observations(rows):
    if canonical(rows) != canonical(expected()):
        raise ValueError('Subprocess service pending ownership, fallback order or raw error identity differs')


def validate_runtime(report):
    if not isinstance(report, dict) or set(report) != {'observations', 'root', 'module', 'python'}:
        raise ValueError('Subprocess ownership runtime fields are incomplete')
    if (not isinstance(report['root'], str) or not Path(report['root']).is_absolute()
            or not isinstance(report['module'], str)
            or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/__init__.py').resolve()
            or canonical(report['python']) != '[3,8,10]'):
        raise ValueError('Subprocess ownership runtime is not the declared Python 3.8.10 product')
    validate_observations(report['observations'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed'}
    try:
        def reference(*arguments):
            return subprocess.check_output(['git', '-C', str(ROOT / 'reference')] + list(arguments), encoding='utf-8').strip()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        if reference('rev-parse', 'HEAD') != target or reference('status', '--porcelain'):
            raise ValueError('Subprocess ownership reference differs from the clean pinned target')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_name(output.stem + '.' + name + '.json') for name in ('source', 'native')]
        for path in paths:
            path.unlink(missing_ok=True)
        node = shutil.which('node')
        if node is None:
            raise ValueError('Subprocess ownership source observations require Node')
        commands = [[node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
            'run', '--config', str(ROOT / 'scripts/oracles/vitest.subprocess-ownership-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/subprocess_ownership_python.py'), str(paths[1])]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT),
                env=dict(os.environ, SUBPROCESS_OWNERSHIP_OUTPUT=str(paths[0])), capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Subprocess ownership observation runner failed: ' + str(index))
        original, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        validate_observations(original)
        validate_runtime(native)
        if native['root'] != str(ROOT) or canonical(original) != canonical(native['observations']):
            raise ValueError('Subprocess ownership fresh source/native observations differ')
        if report['inputSha256'] != hashes() or reference('rev-parse', 'HEAD') != target or reference('status', '--porcelain'):
            raise ValueError('Subprocess ownership inputs changed during frozen observations')
        report.update(status='passed', cases=4, scope='Actual LocalSubprocessRuntime at four controlled handle boundaries; no actual system Host exit, whole process tree, terminal backend or Win7 certification.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
