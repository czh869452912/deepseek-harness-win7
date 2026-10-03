import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
NAMES = ('connect-resolve', 'connect-reject', 'initial-list', 'resync-list', 'resync-reject', 'queued-resync')
INPUTS = ['scripts/mcp_disposal_oracle.py', 'scripts/oracles/mcp_disposal_python.py',
    'scripts/oracles/mcp_disposal.probe.spec.ts', 'scripts/oracles/mcp_factory_disposal.probe.spec.ts',
    'scripts/oracles/vitest.mcp-disposal-probe.config.mts', 'scripts/oracles/vitest.mcp-factory-disposal-probe.config.mts',
    'scripts/oracles/vitest.acp.config.mts', 'scripts/oracles/official/package-lock.json',
    'dsh/mcp/connection.py', 'dsh/mcp/tools.py', 'dsh/mcp/transport.py', 'dsh/mcp/content.py',
    'tests/test_mcp_disposal_source.py', 'tests/test_mcp_disposal_observer.py',
    'reference/packages/mcp/mcp-client/src/connection.ts', 'reference/packages/mcp/mcp-client/src/tools.ts',
    'reference/packages/mcp/mcp-client/src/transport.ts']


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def expected():
    old, late = 'mcp__controlled__old', 'mcp__controlled__late'
    rows = []
    for name in NAMES:
        resync = name.startswith('resync-') or name == 'queued-resync'
        trace = [['create', 1], ['connect']]
        if resync:
            trace += [['fetch', 'tools/list'], ['register', old], ['fetch', 'tools/list']]
        elif name == 'initial-list':
            trace += [['fetch', 'tools/list']]
        trace += [['close']]
        if name == 'connect-reject':
            trace += [['close']]
        if resync:
            trace += [['unregister', old]]
        if name in ('initial-list', 'resync-list', 'queued-resync'):
            trace += [['register', late], ['unregister', late]]
        outcome = {} if resync else {'error': {'name': 'Error', 'message':
            'controlled disposed connect' if name == 'connect-reject' else 'mcp-client(controlled): initial connection failed'}}
        logs = [['info', 'mcp-client(controlled): tool list changed, re-syncing']] * (
            2 if name == 'queued-resync' else 1 if resync else 0)
        rows.append({'name': name, 'before': [old] if resync else [], 'after': [],
            'outcome': outcome, 'trace': trace, 'logs': logs})
    factory = {'outcome': {'name': 'TypeError', 'message': 'Invalid URL', 'code': 'ERR_INVALID_URL'},
        'logs': [['warn', 'mcp-client(controlled): connection attempt failed: TypeError: Invalid URL'],
            ['error', 'mcp-client(controlled): generation did not close within 5000ms during disposal — server shutdown may be incomplete']]}
    return {'supervisor': rows, 'factory': factory}


def validate_observations(value):
    if canonical(value) != canonical(expected()):
        raise ValueError('MCP disposal raw ownership, queued swaps, errors or shutdown diagnostics differ')


def validate_runtime(report):
    if not isinstance(report, dict) or set(report) != {'supervisor', 'factory', 'root', 'module', 'python'}:
        raise ValueError('MCP disposal runtime observations are incomplete')
    if (not isinstance(report['root'], str) or not Path(report['root']).is_absolute()
            or not isinstance(report['module'], str)
            or Path(report['module']).resolve() != (Path(report['root']) / 'dsh/__init__.py').resolve()
            or canonical(report['python']) != '[3,8,10]'):
        raise ValueError('MCP disposal runtime is not the declared Python 3.8.10 product')
    validate_observations({name: report[name] for name in ('supervisor', 'factory')})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed'}
    try:
        def reference(*arguments):
            return subprocess.check_output(['git', '-C', str(ROOT / 'reference')] + list(arguments), encoding='utf-8').strip()
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        if reference('rev-parse', 'HEAD') != target or reference('status', '--porcelain'):
            raise ValueError('MCP disposal reference differs from the clean pinned target')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        paths = [output.with_name(output.stem + '.' + name + '.json') for name in ('source', 'factory', 'native')]
        for path in paths:
            path.unlink(missing_ok=True)
        node = shutil.which('node')
        if node is None:
            raise ValueError('MCP disposal source observations require Node')
        environment = dict(os.environ, MCP_DISPOSAL_OUTPUT=str(paths[0]), MCP_FACTORY_DISPOSAL_OUTPUT=str(paths[1]))
        commands = [[node, '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
            'run', '--config', str(ROOT / ('scripts/oracles/vitest.' + name + '-probe.config.mts'))]
            for name in ('mcp-disposal', 'mcp-factory-disposal')]
        commands += [[sys.executable, str(ROOT / 'scripts/oracles/mcp_disposal_python.py'), str(paths[2])]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('MCP disposal observation runner failed: ' + str(index))
        source = {'supervisor': json.loads(paths[0].read_text(encoding='utf-8')),
            'factory': json.loads(paths[1].read_text(encoding='utf-8'))}
        native = json.loads(paths[2].read_text(encoding='utf-8'))
        validate_observations(source)
        validate_runtime(native)
        if native['root'] != str(ROOT) or canonical(source) != canonical({name: native[name] for name in source}):
            raise ValueError('MCP disposal fresh source/native observations differ')
        if report['inputSha256'] != hashes() or reference('rev-parse', 'HEAD') != target or reference('status', '--porcelain'):
            raise ValueError('MCP disposal inputs changed during frozen observations')
        report.update(status='passed', cases=7, scope='Six actual source supervisor observations at controlled SDK/fetch barriers and one actual SDK invalid-URL disposal; no full SDK, real network cancellation or Win7 certification.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
