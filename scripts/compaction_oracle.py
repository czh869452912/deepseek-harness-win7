"""Compare pinned/native compaction with exact reviewed route/metadata bugs."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUG_TARGET = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
BUG_CASE = dict(mode='embedded-nul-routes', kind='config', config=dict(modelPolicies=[
    dict(provider='a\0b', model='c', maxTokens=1), dict(provider='a', model='b\0c', maxTokens=2)]),
    target=dict(provider='a', model='b\0c'), window=1000)
SUMMARY_BUG_CASE = dict(mode='transaction-private-fields', kind='transaction', marker=False)


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-16-le', 'surrogatepass')


def reviewed_route_key_difference(left, right, spec, target):
    if target != BUG_TARGET or spec != BUG_CASE:
        return False
    expected_left = dict(mode='embedded-nul-routes', error=True, targetKey=None,
        message='BasicCompactionConfig: duplicate model policy for a/b\0c')
    config = dict(thresholdRatio=0.8, retainRatio=0.16, summarizationProvider='', summarizationModel='',
        maxTokens=8192, compactionRetries=1, maxOverflowRetries=1, auto=True,
        modelPolicies=copy.deepcopy(BUG_CASE['config']['modelPolicies']))
    policy = dict(target=BUG_CASE['target'], thresholdRatio=0.8, retainRatio=0.16, summarizationProvider='',
        summarizationModel='', maxTokens=2, compactionRetries=1, maxOverflowRetries=1)
    compact = {key: value for key, value in policy.items() if key != 'retainRatio'}
    compact.update(contextWindow=1000, thresholdTokens=800, retainTokens=160)
    expected_right = dict(mode='embedded-nul-routes', config=config, policy=policy, compact=compact, frozen=True)
    return wire(left) == wire(expected_left) and wire(right) == wire(expected_right)


def reviewed_summary_metadata_difference(left, right, spec, target):
    if target != BUG_TARGET or spec != SUMMARY_BUG_CASE:
        return False
    expected = dict(mode='transaction-private-fields',
        inputs=[dict(keys=['messages', 'system'], system='original prefix',
            text=['important facts ' * 300], routed=dict(provider='old', model='old-model'), sameSignal=True)],
        outcome=dict(shadowedSeqs=[0], shadowedTokenCount=1208),
        summaries=[dict(sourceCommandId='real-command', summary=[dict(type='text', text='custom checkpoint')],
            rawOutput=[dict(type='text', text='raw')], shadowedRange=dict(start=0, end=0), shadowedSeqs=[0],
            shadowedTokenCount=1208, provider='custom', model='template', sameIdentity=True)],
        flushes=0, generation=1, nodes=[5, 1],
        events=[dict(type=kind, error=False) for kind in ('compaction/start', 'compaction/summary', 'compaction/end')])
    expected_left = copy.deepcopy(expected)
    expected_left['outcome']['shadowedTokenCount'] = -1
    expected_left['summaries'][0]['shadowedTokenCount'] = -1
    return wire(left) == wire(expected_left) and wire(right) == wire(expected)


def comparable(row, spec):
    result = copy.deepcopy(row)
    # Error prose is language-specific; validation and the exact target must agree.
    if spec['kind'] == 'config' and result.get('error') is True:
        result.pop('message', None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.goose/out/compaction-paired.json')
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error', cases=[])
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        if actual != target:
            raise ValueError('reference differs from target')
        report['target_upstream'] = target
        specs = json.loads((ROOT / 'scripts/oracles/compaction-cases.json').read_text(encoding='utf-8'))
        specs += json.loads((ROOT / 'scripts/oracles/compaction-invariant-cases.json').read_text(encoding='utf-8'))
        specs += json.loads((ROOT / 'scripts/oracles/error-chain-cases.json').read_text(encoding='utf-8'))
        specs += json.loads((ROOT / 'scripts/oracles/error-transaction-cases.json').read_text(encoding='utf-8'))
        modes = [spec['mode'] for spec in specs]
        if not modes or len(set(modes)) != len(modes):
            raise ValueError('empty or duplicate case identities')
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        commands = [['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.compaction-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/compaction_python.py', str(paths[1])]]
        env = dict(os.environ, COMPACTION_OUTPUT=str(paths[0]))
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            result = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=45)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError('runner %d failed (%d)' % (index, result.returncode))
            rows = json.loads(paths[index].read_text(encoding='utf-8'))
            if [row['mode'] for row in rows] != modes:
                raise ValueError('missing, duplicate or unexpected observations')
            observations.append(rows)
        for spec, left, right in zip(specs, *observations):
            status = ('matched' if wire(comparable(left, spec)) == wire(comparable(right, spec))
                else 'reviewed-upstream-bug' if (reviewed_route_key_difference(left, right, spec, target)
                    or reviewed_summary_metadata_difference(left, right, spec, target)) else 'different')
            report['cases'].append(dict(mode=spec['mode'], status=status, upstream=left, python=right))
        report['status'] = 'passed' if all(row['status'] in ('matched', 'reviewed-upstream-bug') for row in report['cases']) else 'different'
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return {'passed': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
