import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.oracles.subprocess_tree_python import NAMES, observe


INPUTS = ['scripts/subprocess_tree_oracle.py', 'scripts/oracles/subprocess_tree_python.py',
    'scripts/oracles/subprocess_tree_peer.py', 'scripts/oracles/subprocess_host_exit_python.py',
    'scripts/oracles/subprocess_host_exit_source.ts', 'scripts/oracles/subprocess_source_host_loader.mjs',
    'dsh/subprocess/local.py', 'dsh/subprocess/service.py', 'dsh/subprocess/types.py',
    'reference/packages/subprocess/subprocess-local/src/index.ts',
    'reference/packages/subprocess/subprocess-local/src/spawn.ts',
    'reference/packages/subprocess/subprocess-local/tests/process-exit.spec.ts',
    'scripts/oracles/official/package-lock.json', 'tests/test_subprocess_physical_tree.py',
    'tests/test_subprocess_tree_source.py', 'tests/test_subprocess_tree_observer.py']


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def expected():
    return [{'name': name, 'observed': {'exitCode': 23 if name == 'direct' else 0,
        'before': {'root': True, 'descendant': True}, 'after': {'root': False, 'descendant': False},
        'stdout': '', 'stderr': ''}} for name in NAMES]


def validate_observations(rows, product_root=None):
    if not isinstance(rows, list) or len(rows) != len(NAMES):
        raise ValueError('Physical tree scenarios are incomplete')
    public = []
    for row in rows:
        fields = {'name', 'observed', 'physical'} | ({'product'} if product_root is not None else set())
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError('Physical tree observation fields differ')
        physical = row['physical']
        if (not isinstance(physical, dict) or set(physical) != {'host', 'root', 'descendant', 'cwd'}
                or any(type(physical[name]) is not int or physical[name] <= 0 for name in ('host', 'root', 'descendant'))
                or len({physical[name] for name in ('host', 'root', 'descendant')}) != 3
                or not isinstance(physical['cwd'], str) or not Path(physical['cwd']).is_absolute()):
            raise ValueError('Physical ownership identities differ')
        if product_root is not None:
            wanted = {'root': str(product_root), 'module': str(product_root / 'dsh/__init__.py'), 'python': [3, 8, 10]}
            if canonical(row['product']) != canonical(wanted):
                raise ValueError('Physical tree imported a foreign runtime')
        public.append({'name': row['name'], 'observed': row['observed']})
    if canonical(public) != canonical(expected()):
        raise ValueError('Physical tree before/after ownership or Host exit differs')
    return public


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
            raise ValueError('Physical tree reference is not the clean pinned source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        source = observe(ROOT, sys.executable, source=True)
        native = observe(ROOT, sys.executable)
        for name, rows in [('source', source), ('native', native)]:
            output.with_name(output.stem + '.' + name + '.json').write_text(
                json.dumps(rows, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        if canonical(validate_observations(source)) != canonical(validate_observations(native, ROOT)):
            raise ValueError('Actual source/native physical trees differ')
        if report['inputSha256'] != hashes():
            raise ValueError('Physical tree inputs changed during observation')
        report.update(status='passed', cases=4,
            scope='Actual Windows root/descendant disposal, abort, terminate and direct Host exit; no terminal, hard-killed Host, unknown orphan or Win7 certification.')
    except Exception as error:
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
