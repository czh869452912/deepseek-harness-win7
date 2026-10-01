"""Compare actual platform/pinned Inspect with native cancellation observations."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.oracles.abort_python import observe

SOURCE_INPUTS = ['scripts/oracles/abort.spec.ts', 'scripts/oracles/vitest.abort-probe.config.mts',
    'scripts/oracles/vitest.agent-lifecycle.config.mts', 'scripts/oracles/vitest.consumers.config.mts',
    'scripts/oracles/vitest.core.config.mts', 'reference/packages/extensions/cordis-host-runner/src/inspect-registry.ts']
SOURCE_INPUTS += ['reference/packages/core/tools/src/index.ts', 'reference/packages/guard/timeout-policy/src/index.ts']
INPUTS = SOURCE_INPUTS + ['scripts/abort_oracle.py', 'scripts/oracles/abort_python.py',
    'dsh/core/abort.py', 'dsh/extensions/inspect_registry.py', 'dsh/core/agent_factory.py',
    'dsh/core/tools.py', 'dsh/core/cancellation.py', 'dsh/session/preparations.py',
    'dsh/llm/deepseek_api_extensions.py', 'dsh/compaction/transaction.py', 'dsh/terminal/service.py']


def digests(paths, normalized=False):
    return {p: hashlib.sha256((ROOT / p).read_text(encoding='utf-8').encode('utf-8') if normalized else (ROOT / p).read_bytes()).hexdigest() for p in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--refresh-source-fixture', action='store_true')
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_output = output.with_suffix('.source.json')
    target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip() == target
    assert not subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain', '--untracked-files=no'], encoding='utf-8').strip()
    report = dict(target_upstream=target, input_sha256=digests(INPUTS), node=subprocess.check_output(['node', '--version'], encoding='utf-8').strip(), python=sys.version.split()[0])
    source_output.unlink(missing_ok=True)
    run = subprocess.run(['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.abort-probe.config.mts'],
        cwd=str(ROOT), env=dict(os.environ, ABORT_OUTPUT=str(source_output)), capture_output=True, timeout=90)
    output.with_suffix('.source.log').write_bytes(run.stdout + run.stderr)
    if run.returncode:
        raise RuntimeError('platform/Inspect source probe failed: ' + run.stderr.decode('utf-8', 'replace'))
    source = json.loads(source_output.read_text(encoding='utf-8'))
    native = asyncio.run(observe())
    report.update(upstream=source, python_observations=native, passed=source == native)
    assert report['input_sha256'] == digests(INPUTS), 'inputs changed during comparison'
    fixture_path = ROOT / 'tests/fixtures/abort-source-observations.json'
    fixture = dict(target_upstream=target, node=report['node'], source_sha256=digests(SOURCE_INPUTS, True), observations=source)
    if options.refresh_source_fixture and report['passed']:
        fixture_path.write_text(json.dumps(fixture, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    else:
        assert json.loads(fixture_path.read_text(encoding='utf-8')) == fixture, 'source fixture drift'
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print('matched', sum(a == b for a, b in zip(source, native)), '/', len(source))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
