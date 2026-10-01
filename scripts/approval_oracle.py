"""Compare pinned approval source observations against native Python services.

Node is a development oracle only; it is not a production Host dependency.
"""
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
from scripts.oracles.approval_python import observe

INPUTS = [
    'scripts/approval_oracle.py', 'scripts/oracles/approval_python.py',
    'scripts/oracles/approval.spec.ts', 'scripts/oracles/vitest.approval.config.mts',
    'scripts/oracles/vitest.agent-lifecycle.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts',
    'reference/packages/interaction/user-approval/src/index.ts',
    'reference/packages/interaction/user-approval/src/invariant.ts',
    'reference/packages/interaction/user-approval/tests/approval.spec.ts',
    'reference/packages/interaction/user-approval/tests/invariant.spec.ts',
    'dsh/interaction/user_approval.py', 'dsh/interaction/approval_invariant.py',
    'dsh/core/abort.py', 'dsh/core/scope.py', 'dsh/core/session/session.py',
    'dsh/core/system_prompt/service.py', 'dsh/diagnostics/invariants.py',
    'dsh/boot/plugin_registry.py', 'dsh/llm/message.py',
]


def digests():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in INPUTS}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_output = output.with_suffix('.source.json')
    suite_output = output.with_suffix('.suite.json')
    for path in (source_output, suite_output):
        if path.exists():
            path.unlink()
    target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
    assert subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip() == target
    assert not subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain', '--untracked-files=no'], encoding='utf-8').strip()
    report = dict(target_upstream=target, input_sha256=digests(), python=sys.version.split()[0],
                  node=subprocess.check_output(['node', '--version'], encoding='utf-8').strip(),
                  product_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT), encoding='utf-8').strip(),
                  tracked_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=str(ROOT), encoding='utf-8').strip()))
    run = subprocess.run(['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config',
                          'scripts/oracles/vitest.approval.config.mts', '--reporter=json', '--outputFile=' + str(suite_output)],
                         cwd=str(ROOT), env=dict(os.environ, APPROVAL_OUTPUT=str(source_output)), capture_output=True, timeout=90)
    output.with_suffix('.source.log').write_bytes(run.stdout + run.stderr)
    report['source_exit_code'] = run.returncode
    if run.returncode:
        report['passed'] = False
    else:
        source = json.loads(source_output.read_text(encoding='utf-8'))
        suite = json.loads(suite_output.read_text(encoding='utf-8'))
        native = asyncio.run(observe())
        # The third test file is the observer. The other two are unchanged
        # upstream assertions, counted separately from native comparisons.
        source_assertions = [result for result in suite['testResults'] if '/reference/' in result['name'].replace('\\', '/')]
        count = sum(len(result['assertionResults']) for result in source_assertions)
        matched = sum(a == b for a, b in zip(source, native))
        report.update(upstream_assertions=count, source_observations=source, python_observations=native,
                      matched=matched, passed=bool(suite['success'] and count == 38 and len(source) == 9 and source == native))
    assert report['input_sha256'] == digests(), 'inputs changed during observation'
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print('approval comparison:', 'passed' if report['passed'] else 'failed', report.get('matched', 0), '/ 9')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
