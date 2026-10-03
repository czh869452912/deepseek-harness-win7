import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
INPUTS = ['scripts/acp_mcp_oracle.py', 'scripts/oracles/acp_mcp_python.py',
    'scripts/oracles/acp_mcp.probe.spec.ts', 'scripts/oracles/acp_mcp_runtime.probe.spec.ts',
    'scripts/oracles/vitest.acp-mcp-probe.config.mts', 'scripts/oracles/vitest.acp-mcp-runtime.config.mts',
    'scripts/oracles/vitest.acp.config.mts', 'scripts/oracles/official/package-lock.json',
    'scripts/oracles/acp-sdk-resolution.mjs', 'scripts/acp_mcp_journey.py',
    'dsh/acp/mcp.py', 'dsh/acp/server.py', 'dsh/acp/model_control.py', 'dsh/acp/session_runtime.py',
    'dsh/core/agent_factory.py', 'dsh/core/agent_loop.py', 'dsh/core/tools.py', 'dsh/core/abort.py',
    'dsh/core/scope.py', 'dsh/boot/plugin_registry.py', 'dsh/cordis/schema.py', 'dsh/cordis/utils.py',
    'dsh/cordis/context.py', 'dsh/cordis/fiber.py',
    'dsh/mcp/client.py', 'dsh/mcp/connection.py', 'dsh/mcp/tools.py', 'dsh/mcp/content.py',
    'dsh/mcp/config.py', 'dsh/mcp/stdio_client.py', 'dsh/mcp/protocol.py',
    'dsh/mcp/schemas.py', 'dsh/mcp/schema_definitions.json',
    'reference/packages/acp/acp/src/mcp.ts', 'reference/packages/acp/acp/src/session.ts',
    'reference/packages/acp/acp/tests/harness.ts', 'tests/test_mcp_stdio_transport.py']


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False, separators=(',', ':'))


def expected_runtime():
    def result(text):
        return {'value': {'content': [{'type': 'text', 'text': text}],
            'structuredContent': {'inherited': None, 'explicit': 'session-owned', 'stale': None}},
            'content': [{'type': 'text', 'text': text}], 'isError': False}
    return {'mcpCapabilities': {'http': True}, 'globalTools': [], 'firstTools': ['mcp__fixture__echo'],
        'firstResult': result('first owned'), 'siblingResult': result('sibling remains'),
        'resumedResult': result('fresh resume'), 'emptyResumeTools': [], 'finalTools': [], 'finalAgents': 0}


def validate_runtime(value):
    if canonical(value) != canonical(expected_runtime()):
        raise ValueError('ACP MCP runtime differs from the declared real-consumer specification')


def validate_process(value):
    expected = {'stdioProcesses': 3, 'stdioCalls': 3, 'stdioReaped': True, 'httpCalls': 1,
        'httpClosed': True, 'acpClosed': True, 'modelRequests': 8,
        'scope': 'Actual canonical ACP process, stdio/HTTP consumers and same-session resume; no external endpoint.'}
    if canonical(value) != canonical(expected):
        raise ValueError('ACP MCP actual process/model ownership observations are incomplete')


def validate_declarations(rows):
    if not isinstance(rows, list) or len(rows) != 58:
        raise ValueError('ACP MCP declaration observations are incomplete')
    identities = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'servers', 'cwd', 'result'}:
            raise ValueError('ACP MCP declaration raw fields differ')
        identity = canonical({'servers': row['servers'], 'cwd': row['cwd']})
        if identity in identities:
            raise ValueError('ACP MCP declaration observation was duplicated')
        identities.append(identity)
        result = row['result']
        if set(result) == {'data'} and isinstance(result['data'], list):
            if len(result['data']) != len(row['servers']):
                raise ValueError('ACP MCP successful declaration lost a provider')
            for config in result['data']:
                if (not isinstance(config, dict) or config.get('failOnStartupError') is not True
                        or not isinstance(config.get('serverName'), str)
                        or re.fullmatch(r'[A-Za-z0-9_-]{1,32}', config['serverName']) is None
                        or canonical(config.get('toolCallTimeoutMs')) != '60000'
                        or canonical(config.get('reconnect')) != canonical({'enabled': True,
                            'initialDelayMs': 500, 'maxDelayMs': 30000, 'maxAttempts': 10})):
                    raise ValueError('ACP MCP successful declaration lost its validated startup/default fields')
            continue
        if (set(result) != {'name', 'message', 'mounted'} or result['name'] != 'AcpMcpConfigError'
                or not isinstance(result['message'], str) or not result['message'].startswith('mcpServers')
                or result['mounted'] != []):
            raise ValueError('ACP MCP declaration failure leaked a mounted provider or lost its error')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'runner-error', 'cases': []}
    try:
        def reference_git(*arguments):
            return subprocess.check_output(['git', '-C', str(ROOT / 'reference')] + list(arguments), encoding='utf-8').strip()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        if reference_git('rev-parse', 'HEAD') != target or reference_git('status', '--porcelain'):
            raise ValueError('ACP MCP reference differs from the pinned target')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        for package, version in [('@modelcontextprotocol/sdk', '1.29.0'), ('@agentclientprotocol/sdk', '1.4.0')]:
            installed = json.loads((ROOT / 'scripts/oracles/official/node_modules' / package / 'package.json').read_text(encoding='utf-8'))
            if installed['version'] != version:
                raise ValueError('ACP MCP SDK version differs from the pinned source dependency: ' + package)
        source, source_runtime = output.with_suffix('.ts.json'), output.with_suffix('.runtime.ts.json')
        native = output.with_suffix('.python.json')
        peer_file = output.with_suffix('.peer.py')
        tests_path = str(ROOT / 'tests')
        sys.path.insert(0, tests_path)
        from test_mcp_stdio_transport import SERVER
        peer_file.write_text(SERVER, encoding='utf-8')
        environment = dict(os.environ, ACP_MCP_OUTPUT=str(source), ACP_MCP_RUNTIME_OUTPUT=str(source_runtime),
            ACP_MCP_PEER=str(peer_file), ACP_MCP_PYTHON=sys.executable)
        commands = [['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
            'run', '--config', 'scripts/oracles/vitest.acp-mcp-probe.config.mts'],
            ['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
            'run', '--config', 'scripts/oracles/vitest.acp-mcp-runtime.config.mts'],
            [sys.executable, 'scripts/oracles/acp_mcp_python.py', str(source), str(peer_file), str(native)]]
        for index, command in enumerate(commands):
            completed = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
            output.with_suffix('.%s.log' % index).write_bytes(completed.stdout + completed.stderr)
            if completed.returncode:
                raise RuntimeError('ACP MCP observer failed: ' + str(index))
        source_rows = json.loads(source.read_text(encoding='utf-8'))
        original_runtime = json.loads(source_runtime.read_text(encoding='utf-8'))
        native_report = json.loads(native.read_text(encoding='utf-8'))
        validate_declarations(source_rows)
        validate_declarations(native_report['declarations'])
        validate_runtime(original_runtime)
        validate_runtime(native_report['runtime'])
        if canonical(source_rows) != canonical(native_report['declarations']):
            raise ValueError('ACP MCP source/native raw declarations differ')
        if report['inputSha256'] != hashes() or reference_git('rev-parse', 'HEAD') != target or reference_git('status', '--porcelain'):
            raise ValueError('ACP MCP observation inputs changed')
        report.update(status='passed', matched=59, cases=[{'mode': 'declarations', 'status': 'matched', 'rows': 58},
            {'mode': 'actual-session-consumers', 'status': 'matched'}],
            scope='58 raw source/native declaration observations and one complete real ACP session/MCP consumer projection; HTTP process and extracted Portable are separate required consumers, not complete ACP or SDK certification.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='runner-error', error=str(error))
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
