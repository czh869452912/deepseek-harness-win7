"""Actual startup/retirement gate; six precisely bound upstream race corrections."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_INPUTS = ['scripts/oracles/cordis-retirement-cases.json', 'scripts/oracles/cordis-retirement.spec.ts',
    'scripts/oracles/vitest.cordis-retirement-probe.config.mts', 'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts',
    'reference/packages/extensions/cordis-host-runner/tests/helpers.ts',
    'reference/packages/extensions/cordis-host-runner/src/index.ts',
    'reference/packages/extensions/cordis-host-runner/src/registry.ts',
    'reference/packages/extensions/cordis-host-runner/src/guard.ts',
    'reference/packages/extensions/cordis-host-runner/src/lifecycle.ts',
    'reference/packages/extensions/cordis-host-runner/src/sandbox.ts']
INPUTS = SOURCE_INPUTS + ['scripts/cordis_retirement_oracle.py', 'scripts/oracles/cordis_retirement_python.py',
    'dsh/extensions/host_runner.py', 'dsh/extensions/cordis_runner_state.py', 'dsh/extensions/cordis_guard.py',
    'dsh/extensions/inspect_registry.py', 'dsh/core/tools.py', 'dsh/cordis/context.py',
    'dsh/cordis/fiber.py', 'dsh/cordis/reflect.py', 'dsh/cordis/utils.py',
    'tests/test_cordis_retirement.py', 'tests/fixtures/cordis-retirement-source-observations.json']
BUG_HASHES = {
    'remove-host-starting': 'd1d0201d7dd652cc09637c1533ca391dfe05a517e858f6025e08f2ac57358379',
    'stop-host-starting': 'ca50946aabd1daf212d42ecb472cc7ffbbffccae0883c1257acd12e4fe5822dd',
    'remove-dual-starting': 'ada73168561dfc1a74893e00f8a29f574b7e889c4a42fa3dc117c6284ff118d1',
    'stop-dual-starting': '9a4c81b7d6d52a8333fac281df138c5127d667fe6bd2f0cf980fb3a29bd7e578',
    'remove-update-starting': '5ffe0d72e4900e585538b53ed8bfd71674303aa13f1c78b3378b5af7ae7c860c',
    'stop-update-starting': '92f34fc7c295beff8a8f808ff0a7418a691c41a78b3d914a4300c5674f0b9b4d',
}


def corrected_observation(source):
    mode = source['mode']
    digest = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')).hexdigest()
    if BUG_HASHES.get(mode) != digest:
        raise ValueError('not the precisely reviewed startup/retirement race')
    result = copy.deepcopy(source)
    removing, client = mode.startswith('remove-'), '-dual-' in mode
    during = copy.deepcopy(source['before'])
    during['endSettled'] = False
    row = during['inventory'][0]
    pid, attempt = row['pluginId'], row['latestRun']
    attempt['status'] = 'cancelled'
    if client:
        rid = attempt.pop('approvalRequestId')
        attempt.pop('requiresApproval')
        attempt['error'] = dict(phase='approval', message='dynamic plugin "{}" was {} before approval'.format(pid, 'removed' if removing else 'stopped'),
            pluginId=pid, packageId=attempt['packageId'], pluginRunId=attempt['pluginRunId'])
        during['events'].append(['cordis/request-run-resolved', dict(requestId=rid, outcome='cancelled')])
    result['during'] = during
    result['started'] = dict(ok=False, message='activation of dynamic plugin "{}" was cancelled during retirement'.format(pid))
    if not client:
        result['started']['reason'] = 'cancelled'
    result['ended'] = dict(ok=True, wasRunning=False) if removing else dict(ok=True)
    after = copy.deepcopy(during)
    del after['endSettled']
    after.update(values=[None, None, None], starting=0)
    if removing:
        after['inventory'] = []
    else:
        attempt = after['inventory'][0]['latestRun']
        attempt['status'] = 'stopped'
        for half in ('host', 'client'):
            if attempt[half]['status'] != 'absent':
                attempt[half] = dict(status='stopped', waitingFor=[])
    result['after'] = after
    return result


def classify(source, native):
    if source == native:
        return 'matched'
    try:
        if corrected_observation(source) == native:
            return 'reviewed-upstream-bug/CORDIS-LIFECYCLE-001'
    except (KeyError, TypeError, ValueError, IndexError):
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
        commands = [['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.cordis-retirement-probe.config.mts'],
            [sys.executable, 'scripts/oracles/cordis_retirement_python.py', str(paths[1])]]
        env = dict(os.environ, CORDIS_RETIREMENT_OUTPUT=str(paths[0]))
        for index, command in enumerate(commands):
            run = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError('runner %d failed (%d)' % (index, run.returncode))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        if any([row['mode'] for row in observations] != modes for observations in (source, native)):
            raise ValueError('missing, duplicate or unexpected observations')
        fixture_path = ROOT / 'tests/fixtures/cordis-retirement-source-observations.json'
        if args.refresh_source_fixture:
            fixture_path.write_text(json.dumps(dict(target_upstream=target, source_sha256=digests(SOURCE_INPUTS, True), observations=source), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        fixture = json.loads(fixture_path.read_text(encoding='utf-8'))
        if fixture != dict(target_upstream=target, source_sha256=digests(SOURCE_INPUTS, True), observations=source):
            raise ValueError('fixture differs from actual pinned observations/inputs')
        report['cases'] = [dict(mode=left['mode'], status=classify(left, right)) for left, right in zip(source, native)]
        report['status'] = 'passed' if all(row['status'] != 'different' for row in report['cases']) else 'different'
        report['input_sha256'] = digests(INPUTS)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'], [(row['mode'], row['status']) for row in report['cases']])
    return {'passed': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
