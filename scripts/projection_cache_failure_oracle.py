import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
NAMES = ('cold-malformed', 'prepared-malformed', 'cold-matching', 'cold-foreign-identity',
    'cold-foreign-cwd', 'cold-version-mismatch', 'cold-beyond-log', 'cold-empty')
INPUTS = ['scripts/projection_cache_failure_oracle.py', 'scripts/oracles/projection_cache_failure_python.py',
    'scripts/oracles/projection_cache_failure.probe.spec.ts', 'scripts/oracles/vitest.projection-cache-failure-probe.config.mts',
    'scripts/oracles/vitest.storage-cache.config.mts', 'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/official/package-lock.json',
    'dsh/session/projection_cache.py', 'dsh/session/projections.py', 'dsh/storage/domain_impl.py',
    'dsh/storage/domain_spec.py', 'dsh/storage/storage_json.py', 'dsh/core/session/session.py',
    'reference/packages/session/session-projection-cache/src/index.ts',
    'reference/packages/session/session-projection/src/index.ts',
    'reference/packages/session/session-projection-cache/tests/cache.spec.ts',
    'tests/test_projection_cache_failure_source.py', 'tests/test_projection_cache_failure_observer.py']


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(',', ':'))


def expected():
    rows = []
    for name in NAMES:
        malformed = name.endswith('malformed')
        observed = {'applied': [] if name == 'cold-malformed' else [1] if name == 'cold-matching' else [0, 1]}
        if name == 'cold-malformed':
            observed['error'] = {'name': 'TypeError', 'message': 'controlled invalid cache value', 'sameParserFailure': True}
        else:
            observed['snapshot'] = {'asOfSeq': 1, 'values': {'controlled/count': 8 if name == 'cold-matching' else 2}}
        observed['document'] = {'version': 4, 'record': {'identity': {'createdAt': 9, 'cwd': '/controlled/cwd'},
            'rows': {'controlled/count': {'ver': 1, 'seq': 0 if malformed else 1,
                'val': 'bad' if malformed else 8 if name == 'cold-matching' else 2}}}}
        rows.append({'name': name, 'observed': observed})
    return rows


def validate_observations(rows):
    if canonical(rows) != canonical(expected()):
        raise ValueError('Projection cache failure, fallback, identity, apply cut or durable record differs')


def validate_runtime(report):
    if (not isinstance(report, dict) or set(report) != {'observations', 'root', 'module', 'python'}
            or not isinstance(report['root'], str) or not Path(report['root']).is_absolute()
            or not isinstance(report['module'], str)
            or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/__init__.py').resolve()
            or canonical(report['python']) != '[3,8,10]'):
        raise ValueError('Projection cache runtime provenance is incomplete')
    validate_observations(report['observations'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed'}
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if actual != target or dirty:
            raise ValueError('Projection cache reference is not the clean pinned source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        workspace = output.with_name(output.stem + '.workspace')
        workspace.mkdir()
        paths = [output.with_name(output.stem + '.' + name + '.json') for name in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Projection cache source requires Node')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run',
            '--config', str(ROOT / 'scripts/oracles/vitest.projection-cache-failure-probe.config.mts')],
            [sys.executable, str(ROOT / 'scripts/oracles/projection_cache_failure_python.py'), str(workspace / 'native'), str(paths[1])]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ,
                PROJECTION_CACHE_WORKSPACE=str(workspace / 'source'), PROJECTION_CACHE_OUTPUT=str(paths[0])),
                capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Projection cache runner failed: ' + str(index))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        validate_observations(source)
        validate_runtime(native)
        if native['root'] != str(ROOT) or canonical(source) != canonical(native['observations']):
            raise ValueError('Projection cache actual source/native observations differ')
        if report['inputSha256'] != hashes():
            raise ValueError('Projection cache inputs changed during observation')
        report.update(status='passed', cases=8,
            scope='Actual JSON storage domain, registry and cache consumers at eight selected read cuts; no complete domain/Web/SQLite/long-history certification.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
