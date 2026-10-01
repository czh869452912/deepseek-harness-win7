"""Compare actual pinned/Python runner journeys, with one exact bug exception."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE_INPUTS = ['scripts/oracles/cordis-runner-cases.json', 'scripts/oracles/cordis-runner.spec.ts',
    'scripts/oracles/vitest.cordis-runner-probe.config.mts', 'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts',
    'reference/packages/extensions/cordis-host-runner/src/index.ts',
    'reference/packages/extensions/cordis-host-runner/src/registry.ts',
    'reference/packages/extensions/cordis-host-runner/src/types.ts',
    'reference/packages/extensions/cordis-host-runner/src/sandbox.ts',
    'reference/packages/extensions/cordis-host-runner/src/guard.ts',
    'reference/packages/extensions/cordis-host-runner/src/lifecycle.ts',
    'reference/packages/extensions/cordis-host-runner/tests/helpers.ts']
INPUTS = SOURCE_INPUTS + ['scripts/cordis_runner_oracle.py', 'scripts/oracles/cordis_runner_python.py',
    'dsh/extensions/host_runner.py', 'dsh/extensions/cordis_runner_state.py',
    'dsh/extensions/inspect_registry.py', 'dsh/core/tools.py', 'dsh/core/json_schema.py',
    'dsh/llm/message.py', 'dsh/core/abort.py', 'dsh/core/cancellation.py',
    'dsh/cordis/context.py', 'dsh/cordis/fiber.py', 'dsh/cordis/reflect.py',
    'dsh/typert/remote.py', 'dsh/typert/dispatch.py', 'tests/test_cordis_runner_state.py',
    'tests/test_cordis_tools_full.py', 'tests/fixtures/cordis-runner-source-observations.json']
SOURCE_GUIDANCE = 'that Service in the returned Plugin inject list or read it with ctx.get(name) and handle undefined.'
NATIVE_GUIDANCE = 'that Service in the plugin.inject list or read it with ctx.get(name) and handle None in Python Host code.'


def native_projection(source):
    """Only the reviewed Host-language guidance changes; all wire data is exact."""
    result = copy.deepcopy(source)
    if source['mode'] == 'actual-host-apply-failure-and-retry':
        def remove_source_stack(value):
            if isinstance(value, list):
                for child in value:
                    remove_source_stack(child)
            elif isinstance(value, dict):
                if 'stack' in value:
                    stack = value['stack']
                    if (value.get('message') != 'fixture apply failure' or not stack.startswith('Error: fixture apply failure\n')
                            or 'at startHostHalf ([workspace]/reference/packages/extensions/cordis-host-runner/src/lifecycle.ts:' not in stack):
                        raise ValueError('source lifecycle stack adaptation drift')
                    del value['stack']
                for child in value.values():
                    remove_source_stack(child)
        remove_source_stack(result)
    for row in result['rows']:
        for message in row['steer']:
            for block in message['content']:
                text = block.get('text', '')
                if text.startswith('Cordis Host handler '):
                    if text.count(SOURCE_GUIDANCE) != 1:
                        raise ValueError('Host-language guidance drift')
                    block['text'] = text.replace(SOURCE_GUIDANCE, NATIVE_GUIDANCE)
    return result


def collision_projection(source):
    if source['mode'] != 'runtime-error-nul-collision' or len(source['rows']) != 6:
        raise ValueError('not the reviewed collision journey')
    result = native_projection(source)
    rows = result['rows']
    if (rows[2]['value'] != dict(ok=False, code='handler-error', message='c', stack='fixture stack')
            or rows[3]['value'] != dict(ok=False, code='handler-error', message='b\0c', stack='fixture stack')
            or len(rows[2]['steer']) != 1 or rows[3]['steer'] or rows[4]['steer']):
        raise ValueError('not the reviewed upstream error collision')
    notification = copy.deepcopy(rows[2]['steer'][0])
    text = notification['content'][0]['text']
    if text.count('host.call("a\\u0000b").') != 1 or text.count('message: c\n') != 1:
        raise ValueError('collision notification drift')
    notification['content'][0]['text'] = text.replace('host.call("a\\u0000b").', 'host.call("a").').replace('message: c\n', 'message: b\0c\n')
    rows[3]['steer'] = [notification]
    return result


def classify(source, native):
    if source == native:
        return 'matched'
    try:
        if source['mode'] == 'runtime-error-nul-collision' and collision_projection(source) == native:
            return 'reviewed-upstream-bug/CORDIS-RUNTIME-001-with-Python-guidance'
        if native_projection(source) == native:
            return 'matched-with-Python-lifecycle-stack' if source['mode'] == 'actual-host-apply-failure-and-retry' else 'matched-with-Python-guidance'
    except (ValueError, KeyError, TypeError, IndexError):
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
        specs = json.loads((ROOT / 'scripts/oracles/cordis-runner-cases.json').read_text(encoding='utf-8'))
        modes = [spec['mode'] for spec in specs]
        if not modes or len(set(modes)) != len(modes):
            raise ValueError('empty or duplicate journeys')
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        for path in paths:
            if path.exists():
                path.unlink()
        commands = [['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.cordis-runner-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/cordis_runner_python.py', str(paths[1])]]
        env = dict(os.environ, CORDIS_RUNNER_OUTPUT=str(paths[0]))
        for index, command in enumerate(commands):
            run = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError('runner %d failed (%d)' % (index, run.returncode))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        if any([row['mode'] for row in observation] != modes for observation in (source, native)):
            raise ValueError('missing, duplicate or unexpected journeys')
        fixture_path = ROOT / 'tests/fixtures/cordis-runner-source-observations.json'
        if args.refresh_source_fixture:
            fixture_path.write_text(json.dumps(dict(target_upstream=target, source_sha256=digests(SOURCE_INPUTS, True), observations=source), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        fixture = json.loads(fixture_path.read_text(encoding='utf-8'))
        if fixture != dict(target_upstream=target, source_sha256=digests(SOURCE_INPUTS, True), observations=source):
            raise ValueError('source fixture does not match actual pinned observations/inputs')
        for left, right in zip(source, native):
            report['cases'].append(dict(mode=left['mode'], status=classify(left, right), steps=len(left['rows'])))
        report['status'] = 'passed' if all(row['status'] != 'different' for row in report['cases']) else 'different'
        report['input_sha256'] = digests(INPUTS)
        report['step_count'] = sum(row['steps'] for row in report['cases'])
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'], [(row['mode'], row['status']) for row in report['cases']])
    return {'passed': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
