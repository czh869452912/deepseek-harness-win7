import argparse
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXPECTED_PATH = ROOT / 'scripts/oracles/mcp_http_expected.json'
with EXPECTED_PATH.open(encoding='utf-8') as stream:
    EXPECTED = json.load(stream)
INPUTS = [
    'scripts/mcp_http_oracle.py', 'scripts/oracles/mcp_http_expected.json',
    'scripts/oracles/mcp_http_python.py', 'scripts/oracles/mcp_http_peer.py',
    'scripts/oracles/mcp_http.probe.spec.ts', 'scripts/oracles/vitest.mcp-http-probe.config.mts',
    'scripts/oracles/vitest.acp.config.mts', 'scripts/oracles/acp-sdk-resolution.mjs',
    'scripts/oracles/official/package-lock.json', 'dsh/mcp/http_client.py', 'dsh/mcp/protocol.py',
    'dsh/mcp/stdio_client.py', 'dsh/mcp/transport.py', 'dsh/mcp/client.py', 'dsh/mcp/connection.py',
    'dsh/mcp/config.py', 'dsh/mcp/content.py', 'dsh/mcp/tools.py', 'dsh/mcp/schemas.py',
    'dsh/mcp/schema_definitions.json', 'dsh/core/tools.py', 'dsh/core/abort.py',
    'reference/packages/mcp/mcp-client/src/transport.ts',
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def validate_observations(rows):
    require(canonical(rows) == canonical(EXPECTED['observations']), 'HTTP observations differ from the bounded original specification')


def validate_runtime_report(report):
    validate_observations(report.get('observations'))
    require(canonical(report.get('consumer')) == canonical({'registered': True, 'output': 'controlled consumer',
        'retired': True, 'closed': True, 'writers': 0, 'tasks': 0, 'pending': 0, 'childExited': True}),
        'HTTP actual ToolsService consumer or owned resources are incomplete')
    version = report.get('python')
    parts = version.split() if isinstance(version, str) else []
    require(bool(parts) and parts[0] == '3.8.10', 'HTTP runtime is not Python 3.8.10')
    root, module = report.get('root'), report.get('module')
    require(isinstance(root, str) and isinstance(module, str) and Path(root).is_absolute()
        and Path(module).resolve().parent == Path(root).resolve() / 'dsh', 'HTTP module provenance does not match the observed product')


def main():
    parser = argparse.ArgumentParser(description='Verify bounded source SDK/native HTTP observations and actual owned consumer.')
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'runner-error', 'cases': []}
    try:
        def reference_git(*arguments):
            return subprocess.check_output(['git', '-C', str(ROOT / 'reference')] + list(arguments), encoding='utf-8').strip()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        require(target == EXPECTED['target_upstream'] and reference_git('rev-parse', 'HEAD') == target
            and not reference_git('status', '--porcelain'), 'reference differs from the pinned HTTP target')
        package = json.loads((ROOT / 'scripts/oracles/official/node_modules/@modelcontextprotocol/sdk/package.json').read_text(encoding='utf-8'))
        require(package['version'] == EXPECTED['sdk_version'], 'HTTP source SDK version is not pinned')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        source, native = output.with_suffix('.ts.json'), output.with_suffix('.python.json')
        source_directory = output.parent / (output.stem + '-source-peers')
        source_directory.mkdir(exist_ok=True)
        require(not any(source_directory.iterdir()), 'HTTP source peer directory must be fresh')
        environment = dict(os.environ, MCP_HTTP_OUTPUT=str(source), MCP_HTTP_DIRECTORY=str(source_directory),
            MCP_FIXTURE_PYTHON=sys.executable, MCP_HTTP_PEER=str(ROOT / 'scripts/oracles/mcp_http_peer.py'))
        for index, command in enumerate([
            ['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
                'run', '--config', 'scripts/oracles/vitest.mcp-http-probe.config.mts'],
            [sys.executable, 'scripts/oracles/mcp_http_python.py', str(native)],
        ]):
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            require(result.returncode == 0, 'HTTP observer failed: ' + str(index))
        source_rows = json.loads(source.read_text(encoding='utf-8'))
        native_report = json.loads(native.read_text(encoding='utf-8'))
        validate_observations(source_rows)
        validate_runtime_report(native_report)
        report.update(status='passed', matched=len(source_rows), cases=[{'mode': row['mode'], 'status': 'matched'} for row in source_rows],
            scope='Sixteen exact original factory/SDK/native HTTP rows and actual ToolsService/close ownership at declared admission barriers; TLS, redirects, resumable streams, ACP and Win7 are separate unaccepted scopes.')
        require(report['inputSha256'] == hashes(), 'HTTP observation inputs changed')
        require(reference_git('rev-parse', 'HEAD') == target and not reference_git('status', '--porcelain'), 'reference changed')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(status='runner-error', error=str(error))
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
