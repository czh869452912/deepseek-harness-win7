import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dsh.acp.parameter_schemas import (
    DESERIALIZE_SOURCE_SHA256, PARAMETER_SCHEMAS, SCHEMA_SOURCE_SHA256, SDK_VERSION,
)

FRAMING = ['frames', 'errors', 'batch', 'responses', 'cancel', 'duplicate', 'eof', 'tail', 'eof-parse', 'eof-request']
OUTGOING = ['result', 'remote-error', 'invalid', 'unknown', 'preabort', 'cancel', 'close', 'write-failure', 'mapper']


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def input_cases():
    cases = json.loads((ROOT / 'scripts/oracles/acp_stdio_cases.json').read_text(encoding='utf-8'))
    generator = random.Random(20261003)
    values = [None, False, True, 0, 1, -1, 1.25, '', 'text', [], {}, [None, 42, 'x'], {'_meta': None, 'extra': True}]
    cases['fuzz'] = []
    for index in range(800):
        seed = generator.choice(cases['parameters'])
        params = seed.get('params')
        if isinstance(params, dict):
            params = dict(params)
            params[generator.choice(list(params) + ['_meta', 'extra'])] = generator.choice(values)
        else:
            params = generator.choice(values)
        cases['fuzz'].append({'mode': 'fuzz-%04d' % index, 'method': seed['method'], 'params': params})
    return cases


def validate_observations(rows, cases):
    modes = ['framing/' + mode for mode in FRAMING] + ['outgoing/' + mode for mode in OUTGOING]
    modes += ['bytes/' + case['mode'] for case in cases['bytes']]
    modes += ['params/' + case['mode'] for case in cases['parameters'] + cases['fuzz']]
    require(len(modes) == 906 and len(set(modes)) == len(modes), 'invalid observation inventory')
    require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows) and
            [row.get('mode') for row in rows] == modes, 'missing, duplicated or reordered observation')
    for row in rows:
        mode = row['mode']
        if mode.startswith('params/'):
            require(set(row) in ({'mode', 'value'}, {'mode', 'error'}), 'lost parameter observation')
            if 'error' in row:
                require(set(row['error']) == {'code', 'message', 'data'} and
                        row['error']['code'] == -32602 and row['error']['message'] == 'Invalid params' and
                        isinstance(row['error']['data'], dict), 'lost formatted parameter error')
            continue
        fields = {'mode', 'output'}
        if mode in ('framing/cancel', 'framing/duplicate'):
            fields |= {'wrongTypeAborted', 'cancelled'}
            require(row['wrongTypeAborted'] is False and row['cancelled'] ==
                    ([True] if mode.endswith('/cancel') else [False, True]), 'lost typed cancellation identity')
        elif mode == 'framing/eof':
            fields.add('aborted')
            require(row['aborted'] is True, 'EOF did not abort owned request')
        elif mode == 'framing/tail':
            fields.add('messages')
            require(row['messages'] == [{'jsonrpc': '2.0', 'id': 1, 'method': 'echo', 'params': '中文😀'}], 'lost unterminated tail')
        elif mode.startswith('outgoing/'):
            fields |= {'settledBeforeReply', 'outcome', 'closed'}
            require(type(row['settledBeforeReply']) is bool and type(row['closed']) is bool and
                    isinstance(row['outcome'], dict), 'lost outgoing state')
            require(row['settledBeforeReply'] is (mode == 'outgoing/write-failure') and
                    row['closed'] is (mode in ('outgoing/close', 'outgoing/write-failure')), 'incorrect outgoing ownership')
        require(set(row) == fields and isinstance(row['output'], list), 'lost raw wire fields')
    observed = {row['mode']: row for row in rows}
    require(observed['framing/frames']['output'][0] == {'jsonrpc': '2.0', 'id': None, 'error': {
        'code': -32700, 'message': 'Parse error'}}, 'missing parse error anchor')
    require(len(observed['framing/batch']['output']) == 2 and
            len(observed['framing/batch']['output'][0]) == 4, 'empty batch observation')
    for mode in ('preabort', 'cancel'):
        output = observed['outgoing/' + mode]['output']
        require(len(output) == 2 and output[1] == {'jsonrpc': '2.0', 'method': '$/cancel_request',
                'params': {'requestId': 0}}, 'lost outgoing cancellation frame')
    require(any('value' in row for row in rows if row['mode'].startswith('params/initialize')) and
            any('error' in row for row in rows if row['mode'].startswith('params/initialize')), 'vacuous initialize validation')


def main():
    parser = argparse.ArgumentParser(description='Compare production ACP stdio with pinned SDK wire and schema behavior.')
    parser.add_argument('--output', type=Path, default=ROOT / '.goose/out/acp-stdio-paired.json')
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'runner-error', 'cases': []}
    try:
        def reference_git(*arguments):
            return subprocess.check_output(['git', '-C', str(ROOT / 'reference')] + list(arguments), encoding='utf-8').strip()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference differs from target')
        inputs = ['dsh/acp/' + name + '.py' for name in ('rpc', 'parameters', 'parameter_schemas', 'stdio', 'errors', 'server', 'session_runtime')]
        inputs += ['dsh/bundle/acp_app.py', 'dsh/boot/plugin_registry.py', 'scripts/acp_stdio_oracle.py',
                   'dsh/boot/profile_boot.py', 'dsh/session/projection_cache.py',
                   'scripts/oracles/acp_stdio_cases.json', 'scripts/oracles/acp_stdio_sdk.mjs',
                   'scripts/oracles/acp_stdio_python.py', 'scripts/oracles/acp_parameter_schema.mjs',
                   'tests/test_acp_stdio.py', 'tests/test_acp_stdio_journey.py', 'tests/test_acp_stdio_oracle.py',
                   'scripts/oracles/official/package-lock.json']
        sdk = 'scripts/oracles/official/node_modules/@agentclientprotocol/sdk/'
        inputs += [sdk + name for name in ('package.json', 'dist/jsonrpc.js', 'dist/stream.js',
                                          'dist/schema/zod.gen.js', 'dist/schema-deserialize.js')]
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in inputs}
        report.update(target_upstream=target, inputSha256=hashes())
        cases = input_cases()
        case_path, schema_path = output.with_suffix('.cases.json'), output.with_suffix('.schema.json')
        case_path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        commands = [['node', 'scripts/oracles/acp_parameter_schema.mjs', str(schema_path)],
                    ['node', 'scripts/oracles/acp_stdio_sdk.mjs', str(case_path), str(paths[0])],
                    [sys.executable, 'scripts/oracles/acp_stdio_python.py', str(case_path), str(paths[1])]]
        for index, command in enumerate(commands):
            (schema_path if index == 0 else paths[index - 1]).unlink(missing_ok=True)
            completed = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ), capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(completed.stdout + completed.stderr)
            require(completed.returncode == 0, 'runner %d failed (%d)' % (index, completed.returncode))
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
        require(schema == {'sdkVersion': SDK_VERSION, 'schemaSourceSha256': SCHEMA_SOURCE_SHA256,
                          'deserializeSourceSha256': DESERIALIZE_SOURCE_SHA256, 'schemas': PARAMETER_SCHEMAS}, 'generated schema drift')
        observations = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        for rows in observations:
            validate_observations(rows, cases)
        report['cases'] = [{'mode': left['mode'], 'status': 'matched' if json.dumps(left, sort_keys=True) ==
                            json.dumps(right, sort_keys=True) else 'different', 'upstream': left, 'python': right}
                           for left, right in zip(*observations)]
        report['status'] = 'matched' if all(row['status'] == 'matched' for row in report['cases']) else 'different'
        report['caseSha256'] = hashlib.sha256(case_path.read_bytes()).hexdigest()
        require(report['inputSha256'] == hashes(), 'observation inputs changed during run')
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference changed during run')
        report['scope'] = '906 raw SDK wire/schema observations; nine mounted ACP methods only. Real process and Portable ownership require separate journeys. MCP, permissions and subagent remain outside A3.'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='runner-error', error=str(error))
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return {'matched': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
