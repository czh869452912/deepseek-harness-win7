"""Verify the current Windows/Python 3.8 candidate, including real browser lanes.

Node and Chromium are development observers, not Portable dependencies.
Dirty previews are explicitly non-publishable; Win7 certification is separate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NODE_VERSION = 'v22.22.2'
PORTABLE_ARCHIVE = 'dist/dsh-win7-portable-v0.1.0.zip'
PAIRED_DRIVERS = (
    'agent_factory', 'agent_config', 'session_recovery', 'session_live',
    'session_prepared', 'session_storage', 'session_projection', 'deepseek',
    'pi', 'storage_cache', 'workflow_ralph', 'repeat_tool', 'token_meter',
    'pruner', 'compaction', 'maintenance', 'timeout_policy', 'abort',
    'approval', 'inspect', 'cordis_guard', 'cordis_runner',
    'cordis_retirement', 'cordis_tools', 'acp_sessions',
)
OFFICIAL_CONFIGS = ('consumers', 'agent-lifecycle', 'session-recovery', 'session-projection', 'acp')
REQUIRED_REGRESSION = {
    'test_native_web_browser': {
        'test_original_browser_native_host_cordis_lifecycle[lifecycle]',
        'test_original_browser_native_host_cordis_lifecycle[inspect]',
    },
    'test_python_web_plugin': {'test_original_browser_installed_python_web_package_journey'},
    'test_python_client_build': {
        'test_original_browser_built_creative_source_restart_upgrade_rollback[host]',
        'test_original_browser_built_creative_source_restart_upgrade_rollback[session]',
    },
    'test_portable_smoke': {
        'test_smoke_dist_portable_directory[' + profile + ']'
        for profile in ('minimal', 'standard', 'creative', 'web', 'headless')
    },
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*arguments, root=None):
    return subprocess.check_output(['git', '-C', str(root or ROOT)] + list(arguments),
                                   encoding='utf-8').strip()


def source_snapshot():
    names = subprocess.check_output(
        ['git', '-C', str(ROOT), 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        encoding='utf-8').split('\0')
    return {name: digest(ROOT / name) for name in sorted(set(names))
            if name and (ROOT / name).is_file()}


def release_environment(browser):
    environment = {name: value for name, value in os.environ.items()
                   if not re.search(r'(?:^|_)(?:API_KEY|API_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|OAUTH_TOKEN)$', name, re.I)
                   and name.upper() not in ('DSH_HOME', 'PYTHONPATH', 'PYTHONHOME')}
    environment['DSH_TEST_CHROMIUM'] = str(browser)
    return environment


def run(command, name, output, accepted=(0,), env=None, timeout=600, cwd=None):
    print(name, flush=True)
    with (output / (name + '.log')).open('w', encoding='utf-8') as stream:
        result = subprocess.run(command, cwd=str(cwd or ROOT), stdout=stream,
                                stderr=subprocess.STDOUT, env=env, timeout=timeout)
    if result.returncode not in accepted:
        raise RuntimeError('%s failed (%d); see %s' % (name, result.returncode, output / (name + '.log')))
    return result.returncode


def prepare_node_dependencies(output, environment):
    npm = shutil.which('npm.cmd')
    if not npm:
        raise RuntimeError('pinned npm must be on PATH for the development oracle')
    for folder in ('scripts/oracles', 'scripts/oracles/official'):
        run([npm, 'ci', '--legacy-peer-deps', '--no-audit', '--no-fund'],
            'node-' + Path(folder).name, output, env=environment, timeout=1200, cwd=ROOT / folder)


def validate_regression(path):
    suites = ET.parse(str(path)).getroot()
    required = {(module, name) for module, names in REQUIRED_REGRESSION.items() for name in names}
    observed = set()
    for case in suites.iter('testcase'):
        key = (case.get('classname', '').split('.')[-1], case.get('name'))
        if case.find('failure') is not None or case.find('error') is not None:
            raise RuntimeError('Regression contains a failure: ' + str(key))
        if key in required:
            if key in observed or case.find('skipped') is not None:
                raise RuntimeError('Required browser/Portable lane did not execute once: ' + str(key))
            observed.add(key)
    if observed != required:
        raise RuntimeError('Required browser/Portable lanes missing: ' + str(sorted(required - observed)))
    return {'required_lanes': len(observed),
            'skipped': sum(case.find('skipped') is not None for case in suites.iter('testcase'))}


def validate_paired(path):
    report = json.loads(path.read_text(encoding='utf-8'))
    if 'cases' in report and not report['cases']:
        raise RuntimeError('Paired gate has no observed cases: ' + str(path))
    if report.get('mismatches') or report.get('passed') is False or report.get('status') in ('failed', 'different'):
        raise RuntimeError('Paired gate contains a failure: ' + str(path))
    if report.get('status') in ('matched', 'passed') or report.get('passed') is True:
        return report
    if (type(report.get('cases')) is int and report['cases'] > 0
            and report.get('matched') == report['cases'] and report.get('mismatches') == []):
        return report
    raise RuntimeError('Paired gate has no successful receipt: ' + str(path))


def validate_extracted(path, archive, candidate):
    report = json.loads(path.read_text(encoding='utf-8'))
    if (report.get('result') != 'passed' or report.get('browser', {}).get('passed') is not True
            or not report.get('runtime') or report.get('runtimeStderr')
            or report.get('frontendFilesChecked', 0) <= 0):
        raise RuntimeError('Extracted runtime/browser acceptance is incomplete')
    if report.get('archiveSha256') != digest(archive) or Path(report['archive']).resolve() != archive.resolve():
        raise RuntimeError('Extracted receipt belongs to a different archive')
    provenance = report.get('provenance', {})
    if provenance.get('product_commit') != candidate['product_commit']:
        raise RuntimeError('Extracted receipt belongs to a different product commit')
    if not candidate['worktree_dirty'] and provenance.get('worktree_dirty') is not False:
        raise RuntimeError('Clean release requires clean archive provenance')
    return report


def verify(args, output):
    if sys.platform != 'win32' or sys.version_info[:3] != (3, 8, 10):
        raise RuntimeError('run this gate with Windows Python 3.8.10')
    browser = Path(args.browser or os.environ.get('DSH_TEST_CHROMIUM', '')).resolve()
    if not browser.is_file():
        raise RuntimeError('a real Chromium executable is required: use --browser or DSH_TEST_CHROMIUM')
    if subprocess.check_output(['node', '--version'], encoding='utf-8').strip() != NODE_VERSION:
        raise RuntimeError('development oracle requires pinned Node ' + NODE_VERSION[1:])
    baseline = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))
    actual = git('rev-parse', 'HEAD', root=ROOT / 'reference')
    if actual != baseline['target_upstream'] or git('status', '--porcelain', root=ROOT / 'reference'):
        raise RuntimeError('initialize an unchanged pinned reference submodule before running the gate')
    candidate = {'product_commit': git('rev-parse', 'HEAD'),
                 'worktree_dirty': bool(git('status', '--porcelain'))}
    if candidate['worktree_dirty'] and not args.allow_dirty:
        raise RuntimeError('release requires a clean checkout; --allow-dirty produces only a non-publishable preview')
    python = str(ROOT / '.venv/Scripts/python.exe')
    environment = release_environment(browser)
    if args.prepare:
        if not Path(python).is_file():
            run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], 'venv', output, env=environment)
        run([python, '-m', 'ensurepip'], 'ensurepip', output, env=environment)
        run([python, '-m', 'pip', 'install', 'pip==25.0.1'], 'installer', output, env=environment)
        run([python, '-m', 'pip', 'install', '--only-binary=:all:', '-r', 'requirements-dev.lock'],
            'python-dependencies', output, env=environment, timeout=1200)
        prepare_node_dependencies(output, environment)
    before = source_snapshot()
    inputs = output / 'inputs.json'
    inputs.write_text(json.dumps(before, indent=2) + '\n', encoding='utf-8')
    run([python, 'scripts/migration.py', 'check'], 'migration-records', output, env=environment)
    run([python, 'scripts/build_portable.py', '--ripgrep-source',
         'scripts/oracles/official/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe'],
        'portable-build', output, env=environment)
    regression = output / 'pytest.xml'
    run([python, '-m', 'pytest', 'tests', '-ra', '--junitxml=' + str(regression)],
        'pytest', output, env=environment, timeout=1800)
    regression_result = validate_regression(regression)
    for config in OFFICIAL_CONFIGS:
        run(['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
             'run', '--config', 'scripts/oracles/vitest.' + config + '.config.mts'],
            'official-' + config, output, env=environment)
    receipts = {}
    for driver in PAIRED_DRIVERS:
        name = driver.replace('_', '-') + '-paired'
        path = output / (name + '.json')
        path.unlink(missing_ok=True)
        run([python, 'scripts/' + driver + '_oracle.py', '--output', str(path)], name, output, env=environment)
        validate_paired(path)
        receipts[name] = digest(path)
    raw = output / 'cordis-raw.json'
    raw.unlink(missing_ok=True)
    run([python, 'scripts/cordis_oracle.py', '--output', str(raw)],
        'cordis-raw', output, accepted=(0, 1), env=environment)
    acceptance = output / 'cordis-acceptance.json'
    acceptance.unlink(missing_ok=True)
    run([python, 'scripts/cordis_acceptance.py', str(raw), '--output', str(acceptance)],
        'cordis-acceptance', output, env=environment)
    if json.loads(acceptance.read_text(encoding='utf-8')).get('result') != 'passed':
        raise RuntimeError('Cordis scoped adaptation was not accepted')
    receipts['cordis-raw'] = digest(raw)
    receipts['cordis-acceptance'] = digest(acceptance)
    archive = ROOT / PORTABLE_ARCHIVE
    extracted = output / 'portable-extracted.json'
    extracted.unlink(missing_ok=True)
    command = [python, 'scripts/verify_portable.py', '--archive', str(archive),
               '--browser', str(browser), '--output', str(extracted)]
    if not candidate['worktree_dirty']:
        command += ['--expected-commit', candidate['product_commit']]
    run(command, 'portable-extracted', output, env=environment)
    validate_extracted(extracted, archive, candidate)
    receipts['portable-extracted'] = digest(extracted)
    if source_snapshot() != before or git('rev-parse', 'HEAD') != candidate['product_commit']:
        raise RuntimeError('candidate inputs changed during verification')
    if git('rev-parse', 'HEAD', root=ROOT / 'reference') != actual or git('status', '--porcelain', root=ROOT / 'reference'):
        raise RuntimeError('reference changed during verification')
    return dict(candidate, result='development-preview' if candidate['worktree_dirty'] else 'passed',
                publishable=not candidate['worktree_dirty'], target_upstream=actual,
                python=sys.version, platform=sys.platform, node=NODE_VERSION, browser=str(browser),
                regression=regression_result, input_manifest_sha256=digest(inputs), receipts=receipts,
                archive=str(archive), archive_sha256=digest(archive),
                scope='Current Windows complete gate; selected paired contracts, original browser and extracted runtime; not full parity or Win7 certification.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Install pinned development dependencies before verification')
    parser.add_argument('--browser', help='Absolute Chromium executable; defaults to DSH_TEST_CHROMIUM')
    parser.add_argument('--allow-dirty', action='store_true', help='Verify a non-publishable development preview, never a release')
    parser.add_argument('--output-dir', type=Path, default=ROOT / '.goose/out/release-gate')
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / 'summary.json'
    summary_path.unlink(missing_ok=True)
    try:
        summary = verify(args, output)
    except Exception as error:
        summary = dict(result='failed', publishable=False, failure=str(error))
    summary_path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(result=summary['result'], publishable=summary['publishable'],
                          reports=str(output), failure=summary.get('failure'))), flush=True)
    return 1 if summary['result'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
