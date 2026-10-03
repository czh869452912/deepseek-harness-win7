import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.oracles.mcp_stdio_python import MODES


INPUTS = ['scripts/mcp_stdio_oracle.py', 'scripts/oracles/mcp_stdio_python.py',
          'scripts/oracles/mcp_stdio_peer.py', 'scripts/oracles/mcp_stdio.probe.spec.ts',
          'scripts/oracles/vitest.mcp-stdio-probe.config.mts', 'scripts/oracles/vitest.acp.config.mts',
          'scripts/oracles/acp-sdk-resolution.mjs', 'scripts/oracles/official/package-lock.json',
          'dsh/mcp/stdio_client.py', 'dsh/mcp/transport.py', 'dsh/core/abort.py',
          'dsh/mcp/schemas.py', 'dsh/mcp/schema_definitions.json',
          'reference/packages/mcp/mcp-client/src/transport.ts',
          'reference/packages/mcp/mcp-client/src/tools.ts']


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def expected_row(mode):
    row = {'mode': mode, 'notifications': [], 'frames': [], 'closed': True, 'reaped': True}
    if mode == 'malformed-then-valid':
        row['protocolErrors'] = []
    def frame(direction, packet):
        if direction == 'sent':
            packet = copy.deepcopy(packet)
            if mode == 'id-decimal':
                packet['id'] = str(packet['id'])
            if mode == 'id-hex':
                packet['id'] = hex(packet['id'])
            if mode == 'id-empty' and packet['id'] == 0:
                packet['id'] = ''
            if mode == 'malformed-then-valid':
                row['frames'].append({'direction': direction, 'packet': dict(packet, extra=True)})
                def missing(name):
                    return dict(expected='string' if name == 'method' else 'object', code='invalid_type',
                        path=[name], message='Invalid input: expected %s, received undefined' % ('string' if name == 'method' else 'object'))
                def unknown(keys):
                    return dict(code='unrecognized_keys', keys=keys, path=[], message='Unrecognized key%s: %s' % (
                        's' if len(keys) > 1 else '', ', '.join(json.dumps(key) for key in keys)))
                issue = dict(code='invalid_union', errors=[
                    [missing('method'), unknown(['result', 'extra'])],
                    [missing('method'), unknown(['id', 'result', 'extra'])],
                    [unknown(['extra'])], [missing('error'), unknown(['result', 'extra'])]], path=[], message='Invalid input')
                row['protocolErrors'].append({'name': 'ZodError', 'message': json.dumps([issue], ensure_ascii=False, indent=2)})
        row['frames'].append({'direction': direction, 'packet': packet})
    if mode == 'missing-executable':
        row['error'] = {'message': 'MCP error -32000: Connection closed', 'code': -32000}
        return row
    frame('received', {'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
          'clientInfo': {'name': 'dsh-mcp-client', 'version': '0.0.1'}}, 'jsonrpc': '2.0', 'id': 0})
    server = {'name': 'controlled', 'version': '1.0'}
    capabilities = {} if mode == 'capabilities-empty' else {'tools': {}}
    if mode == 'cap-logging-array':
        capabilities['logging'] = []
    if mode == 'cap-experimental-false':
        capabilities['experimental'] = {'extension': False}
    frame('sent', {'jsonrpc': '2.0', 'id': 0, 'result': {
          'protocolVersion': 'unsupported' if mode == 'unsupported' else '2025-11-25',
          'capabilities': capabilities, 'serverInfo': server}})
    if mode == 'cap-experimental-false':
        row['error'] = {'message': json.dumps([dict(code='custom', path=['capabilities', 'experimental', 'extension'],
            message='Invalid input')], ensure_ascii=False, indent=2)}
        return row
    if mode == 'unsupported':
        row['error'] = {'message': "Server's protocol version is not supported: unsupported"}
        return row
    frame('received', {'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    row['server'] = server
    frame('received', {'method': 'tools/list', 'jsonrpc': '2.0', 'id': 1})
    if mode == 'notification':
        frame('sent', {'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'})
        row['notifications'] = [{'method': 'notifications/tools/list_changed'}]
    tools = {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]}
    if mode == 'tool-properties-array':
        tools['tools'][0]['inputSchema']['properties'] = {'value': []}
    raw_tools = copy.deepcopy(tools)
    if mode == 'tool-unknown':
        raw_tools['tools'][0]['unknown'] = {'preserveOnlyRawFrame': True}
    if mode == 'tool-annotations-false':
        raw_tools['tools'][0]['annotations'] = False
    frame('sent', {'jsonrpc': '2.0', 'id': 1, 'result': raw_tools})
    if mode == 'tool-annotations-false':
        row['error'] = {'message': json.dumps([dict(expected='object', code='invalid_type', path=['tools', 0, 'annotations'],
            message='Invalid input: expected object, received boolean')], ensure_ascii=False, indent=2)}
        return row
    row['tools'] = tools
    count = 3 if mode == 'out-of-order' else 1
    for index in range(count):
        frame('received', {'method': 'tools/call', 'params': {'name': 'echo', 'arguments': {
              'text': str(index) if mode == 'out-of-order' else '中文😀'}}, 'jsonrpc': '2.0', 'id': index + 2})
    if mode in ('cancel', 'timeout'):
        reason = 'controlled cancel' if mode == 'cancel' else 'McpError: MCP error -32001: Request timed out'
        frame('received', {'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 2, 'reason': reason}})
        row['error'] = {'message': 'MCP error -32001: ' + ('controlled cancel' if mode == 'cancel' else 'Request timed out'), 'code': -32001}
        if mode == 'timeout':
            row['error']['data'] = {'timeout': 20}
    elif mode == 'eof':
        row['error'] = {'message': 'MCP error -32000: Connection closed', 'code': -32000}
    elif mode in ('peer-error', 'peer-error-null'):
        error = {'code': -32602, 'message': 'controlled rejection', 'data': None if mode == 'peer-error-null' else {'invalid': True}}
        frame('sent', {'jsonrpc': '2.0', 'id': 2, 'error': error})
        row['error'] = dict(error, message='MCP error -32602: controlled rejection')
    else:
        row['results'] = [{'content': [{'type': 'text', 'text': str(index) if mode == 'out-of-order' else '中文😀'}]}
                          for index in range(count)]
        for index in reversed(range(count)):
            frame('sent', {'jsonrpc': '2.0', 'id': index + 2, 'result': row['results'][index]})
    return row


def validate_observations(rows):
    require(isinstance(rows, list) and len(rows) == len(MODES), 'missing MCP observations')
    for row, mode in zip(rows, MODES):
        require(json.dumps(row, sort_keys=True) == json.dumps(expected_row(mode), sort_keys=True),
                'incomplete or corrupted MCP observation: ' + mode)


def classify(source, native):
    validate_observations(source)
    validate_observations(native)
    return [{'mode': left['mode'], 'status': 'matched' if left == right else 'different',
             'upstream': copy.deepcopy(left), 'python': copy.deepcopy(right)} for left, right in zip(source, native)]


def validate_runtime_report(report):
    require(isinstance(report, dict), 'missing MCP runtime report')
    validate_observations(report.get('observations'))
    expected = {'registered': True, 'output': 'controlled consumer', 'retired': True, 'childExited': True, 'pending': 0}
    require(json.dumps(report.get('consumer'), sort_keys=True) == json.dumps(expected, sort_keys=True),
            'incomplete MCP consumer ownership')
    version = report.get('python')
    parts = version.split() if isinstance(version, str) else []
    require(bool(parts) and parts[0] == '3.8.10',
            'MCP runtime is not Python 3.8.10')
    require(isinstance(report.get('root'), str) and isinstance(report.get('module'), str)
            and Path(report['root']).is_absolute()
            and Path(report['module']).resolve().parent == Path(report['root']).resolve() / 'dsh',
            'MCP module root does not match the observed product')


def main():
    parser = argparse.ArgumentParser(description='Observe bounded actual MCP stdio SDK/process fields without normalization.')
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'runner-error', 'cases': []}
    try:
        def reference_git(*arguments):
            return subprocess.check_output(['git', '-C', str(ROOT / 'reference')] + list(arguments), encoding='utf-8').strip()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference differs from target')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        environment = dict(os.environ, MCP_OBSERVATIONS_OUTPUT=str(paths[0]), MCP_FIXTURE_PYTHON=sys.executable,
                           MCP_PEER_PATH=str(ROOT / 'scripts/oracles/mcp_stdio_peer.py'))
        commands = [['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
                     'run', '--config', 'scripts/oracles/vitest.mcp-stdio-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/mcp_stdio_python.py', str(paths[1])]]
        observations = []
        for index, command in enumerate(commands):
            paths[index].unlink(missing_ok=True)
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            require(result.returncode == 0, 'MCP observer runner failed: ' + str(index))
            observations.append(json.loads(paths[index].read_text(encoding='utf-8')))
        report['cases'] = classify(*observations)
        report.update(status='passed', matched=len(MODES), scope='Twenty exact bounded stdio provider/SDK/process observations including selected schema projection, malformed envelopes and SDK numeric response correlation. Full supervisor/Tools richness, HTTP/SSE, ACP mounting, subagent and clean Portable acceptance are separate.')
        require(report['inputSha256'] == hashes(), 'observation inputs changed')
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference changed')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='runner-error', error=str(error))
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
