"""Compare actual repeat-guard journeys, allowing one identified upstream bug."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROTO_TARGET = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
PROTO_CASE = dict(mode='proto-key-loss', config=dict(thresholds=[2]), turns=[[
    ['probe', '{"__proto__":{"q":1},"ok":true}'],
    ['probe', '{"__proto__":{"q":2},"ok":true}'],
]])
PROTO_NOTICE = (
    'You are repeating the exact same tool call with identical arguments. '
    'Carefully analyze the previous result before calling again: if the task is '
    'not complete, try a different approach or different arguments instead of '
    'repeating the call.'
)


def wire(value):
    # ECMAScript and Python may store the same UTF-16 string as pairs or code points.
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text.encode('utf-16-le', 'surrogatepass')


def reviewed_proto_difference(upstream, python, spec, target):
    if target != PROTO_TARGET or spec != PROTO_CASE or upstream['mode'] != 'proto-key-loss':
        return False
    expected = dict(content=[dict(type='text', text=PROTO_NOTICE)],
                    source=dict(kind='plugin', plugin='repeat-tool-reminder', form='notice', summary='probe \u00d7 2'))
    if upstream['notices'] != [expected] or upstream['requests'] != [[], [], [PROTO_NOTICE]]:
        return False
    corrected = dict(upstream, notices=[], requests=[[], [], []])
    return wire(corrected) == wire(python)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.goose/out/repeat-tool-paired.json')
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error', cases=[])
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        if target != actual:
            raise ValueError('reference differs from target')
        report['target_upstream'] = target
        specs = json.loads((ROOT / 'scripts/oracles/repeat-tool-cases.json').read_text(encoding='utf-8'))
        modes = [row['mode'] for row in specs]
        if len(modes) != len(set(modes)):
            raise ValueError('duplicate case identities')
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        env = dict(os.environ, REPEAT_TOOL_OUTPUT=str(paths[0]))
        commands = [
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.repeat-tool-probe.config.mts'],
            [sys.executable, 'scripts/oracles/repeat_tool_python.py', str(paths[1])],
        ]
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            result = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=45)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            if result.returncode != 0:
                raise RuntimeError('runner %d failed (%d)' % (index, result.returncode))
            rows = json.loads(paths[index].read_text(encoding='utf-8'))
            if [row['mode'] for row in rows] != modes:
                raise ValueError('missing, duplicate or unexpected observations')
            observations.append(rows)
        for spec, left, right in zip(specs, *observations):
            status = 'matched' if wire(left) == wire(right) else (
                'reviewed-upstream-bug' if reviewed_proto_difference(left, right, spec, target) else 'different')
            report['cases'].append(dict(mode=left['mode'], status=status, upstream=left, python=right))
        report['status'] = 'passed' if all(row['status'] in ('matched', 'reviewed-upstream-bug') for row in report['cases']) else 'different'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    print(report['status'])
    return {'passed': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
