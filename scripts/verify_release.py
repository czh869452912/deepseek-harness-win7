"""Reproduce the Windows/Python 3.8 release gate from a checkout with no caches.

Modern Node is development-only. Versioned frontend assets are explicit inputs;
rebuilding them from the current upstream source belongs to the Web contract batch.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command, name, output, accepted=(0,)):
    print(name, flush=True)
    with (output / (name + '.log')).open('w', encoding='utf-8') as stream:
        result = subprocess.run(command, cwd=str(ROOT), stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode not in accepted:
        raise RuntimeError('%s failed (%d); see %s' % (name, result.returncode, output / (name + '.log')))
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Create .venv and install pinned Python/Node development dependencies')
    args = parser.parse_args(argv)
    if sys.platform != 'win32' or sys.version_info[:3] != (3, 8, 10):
        parser.error('run this gate with Windows Python 3.8.10')
    output = ROOT / '.goose/out/release-gate'
    output.mkdir(parents=True, exist_ok=True)
    # A failed or interrupted rerun must not inherit a previous success marker.
    (output / 'summary.json').unlink(missing_ok=True)
    baseline = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))
    actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    if actual != baseline['target_upstream']:
        raise RuntimeError('initialize the pinned reference submodule before running the gate')
    python = str(ROOT / '.venv/Scripts/python.exe')
    if args.prepare:
        if not Path(python).is_file():
            run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], 'venv', output)
        run([python, '-m', 'ensurepip'], 'ensurepip', output)
        run([python, '-m', 'pip', 'install', 'pip==25.0.1'], 'installer', output)
        run([python, '-m', 'pip', 'install', '--only-binary=:all:', '-r', 'requirements-dev.lock'], 'python-dependencies', output)
        npm = shutil.which('npm.cmd')
        if not npm:
            raise RuntimeError('Node 22.22.2/npm must be on PATH for the development oracle')
        for folder in ('scripts/oracles', 'scripts/oracles/official'):
            run([npm, 'ci', '--prefix', folder, '--legacy-peer-deps', '--no-audit', '--no-fund'],
                'node-' + Path(folder).name, output)
    if subprocess.check_output(['node', '--version'], encoding='utf-8').strip() != 'v22.22.2':
        raise RuntimeError('development oracle requires pinned Node 22.22.2')
    run([python, 'scripts/migration.py', 'check'], 'migration-records', output)
    run([python, 'scripts/build_portable.py', '--ripgrep-source',
         'scripts/oracles/official/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe'], 'portable-build', output)
    run([python, '-m', 'pytest', 'tests', '-ra', '--junitxml=' + str(output / 'pytest.xml')], 'pytest', output)
    run(['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
         'run', '--config', 'scripts/oracles/vitest.consumers.config.mts'], 'official-consumers', output)
    run(['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
         'run', '--config', 'scripts/oracles/vitest.agent-lifecycle.config.mts'], 'official-agent-lifecycle', output)
    run([python, 'scripts/agent_factory_oracle.py', '--output', str(output / 'agent-factory-paired.json')],
        'agent-factory-paired', output)
    run(['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
         'run', '--config', 'scripts/oracles/vitest.session-recovery.config.mts'], 'official-session-recovery', output)
    run([python, 'scripts/session_recovery_oracle.py', '--output', str(output / 'session-recovery-paired.json')],
        'session-recovery-paired', output)
    raw = output / 'cordis-raw.json'
    run([python, 'scripts/cordis_oracle.py', '--output', str(raw)], 'cordis-raw', output, accepted=(0, 1))
    run([python, 'scripts/cordis_acceptance.py', str(raw), '--output', str(output / 'cordis-acceptance.json')],
        'cordis-acceptance', output)
    portable = ROOT / 'dist/dsh-win7-portable'
    boot = """import asyncio, tempfile, pathlib
from dsh.boot.profile import init_profile
from dsh.boot.profile_boot import run_profile
async def main():
    with tempfile.TemporaryDirectory() as directory:
        init_profile(str(pathlib.Path(directory)/'profiles'/'gate'), [], 'startup')
        result = await run_profile({'profile':'gate','dsh_home':directory,'wait_for_exit':False})
        result['shutdown'].shutdown(0)
        await result['shutdown'].wait()
asyncio.run(main())
"""
    run([str(portable / 'python.exe'), '-I', '-c', boot], 'portable-isolated-boot', output)
    summary = {'result': 'passed', 'target_upstream': actual,
               'product_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], encoding='utf-8').strip(),
               'python': sys.version, 'platform': sys.platform,
               'scope': 'Current Windows release gate; Win7 machine/browser deferred; frontend uses versioned byte-checked inputs.'}
    (output / 'summary.json').write_bytes((json.dumps(summary, indent=2) + '\n').encode('utf-8'))
    print('Release gate passed; reports: ' + str(output), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
