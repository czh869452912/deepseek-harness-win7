"""Pinned original/Python tool consumer comparison; no browser/JS Host claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dsh.extensions.cordis_prompt import native_contracts, SOURCE_CONTRACTS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error', cases=[])
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        if subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip() != target:
            raise ValueError('reference differs from pinned target')
        if subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain', '--untracked-files=no'], encoding='utf-8').strip():
            raise ValueError('reference has tracked changes')
        report['target_upstream'] = target
        inputs = ['scripts/cordis_tools_oracle.py', 'scripts/oracles/cordis-tools-cases.json', 'scripts/oracles/cordis-tools.spec.ts',
            'scripts/oracles/cordis_tools_python.py', 'scripts/oracles/vitest.cordis-tools-probe.config.mts',
            'scripts/oracles/vitest.agent-lifecycle.config.mts', 'scripts/oracles/vitest.consumers.config.mts',
            'scripts/oracles/vitest.core.config.mts', 'dsh/extensions/cordis_manager.py', 'dsh/extensions/cordis_tools.py',
            'dsh/extensions/cordis_prompt.py', 'dsh/extensions/cordis_contracts.json', 'dsh/extensions/host_runner.py',
            'dsh/extensions/inspect_registry.py', 'dsh/extensions/inspect_providers.py', 'dsh/core/tools.py',
            'dsh/core/json_schema.py', 'dsh/llm/message.py', 'dsh/core/session/json.py', 'dsh/core/abort.py',
            'dsh/core/cancellation.py', 'dsh/cordis/context.py', 'dsh/cordis/fiber.py', 'dsh/cordis/reflect.py',
            'tests/test_cordis_tools_full.py', 'tests/test_cordis_tool_contracts.py', 'tests/fixtures/cordis-tools-source-observations.json']
        report['input_sha256'] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in inputs}
        specs = json.loads((ROOT / 'scripts/oracles/cordis-tools-cases.json').read_text(encoding='utf-8'))
        modes = [spec['mode'] for spec in specs]
        if not modes or len(set(modes)) != len(modes):
            raise ValueError('empty or duplicate observations')
        paths = [output.with_suffix('.ts.json'), output.with_suffix('.python.json')]
        commands = [['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.cordis-tools-probe.config.mts'],
                    [sys.executable, 'scripts/oracles/cordis_tools_python.py', str(paths[1])]]
        for path in paths:
            if path.exists():
                path.unlink()
        env = dict(os.environ, CORDIS_TOOLS_OUTPUT=str(paths[0]))
        for index, command in enumerate(commands):
            run = subprocess.run(command, cwd=str(ROOT), env=env, capture_output=True, timeout=90)
            output.with_suffix('.%d.log' % index).write_bytes(run.stdout + run.stderr)
            if run.returncode:
                raise RuntimeError('runner %d failed (%d)' % (index, run.returncode))
        source, native = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
        if SOURCE_CONTRACTS != dict(target_upstream=target, **{key: source[key] for key in ('definitions', 'prompt', 'order')}):
            raise ValueError('generated Cordis contract artifact differs from actual original registration')
        contracts = native_contracts()
        if any(native[key] != contracts[key] for key in ('definitions', 'prompt', 'order')):
            raise ValueError('native language adaptations differ from reviewed projection')
        fixture = json.loads((ROOT / 'tests/fixtures/cordis-tools-source-observations.json').read_text(encoding='utf-8'))
        if fixture['target_upstream'] != target or fixture['observations'] != source['cases']:
            raise ValueError('checked-in source observations are stale')
        for path, digest in fixture['source_sha256'].items():
            if hashlib.sha256((ROOT / path).read_text(encoding='utf-8').encode('utf-8')).hexdigest() != digest:
                raise ValueError('source observation input changed: ' + path)
        if any([row['mode'] for row in observation['cases']] != modes for observation in (source, native)):
            raise ValueError('missing, duplicate or unexpected observations')
        for left, right in zip(source['cases'], native['cases']):
            report['cases'].append(dict(mode=left['mode'], status='matched' if left == right else 'different', upstream=left, python=right))
        report['status'] = 'passed' if all(row['status'] == 'matched' for row in report['cases']) else 'different'
        report['metadata'] = dict(status='matched-with-explicit-Python-language-adaptations', prompt_replacements=10,
                                 define_description_replacements=2, host_parameter_description_replacements=1)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'], dict((status, sum(row['status'] == status for row in report['cases'])) for status in ('matched', 'different')))
    return {'passed': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
