"""Verify an actual release ZIP with its extracted, isolated Python runtime.

Node and Chromium are optional development observers, never product runtimes.
The output report intentionally distinguishes this Windows run from Win7 proof.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.mcp_stdio_oracle import validate_runtime_report as validate_mcp_runtime


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            value.update(chunk)
    return value.hexdigest()


def extract(archive, destination):
    # Inspect the whole container before extracting any paths.
    with zipfile.ZipFile(str(archive)) as package:
        seen = set()
        for row in package.infolist():
            name = row.filename.replace('\\', '/')
            parts = name.rstrip('/').split('/')
            if (not parts or parts[0] != 'dsh-win7-portable' or
                    any(part in ('', '.', '..') or ':' in part for part in parts) or
                    name.casefold() in seen or (row.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('invalid Portable archive member: ' + row.filename)
            seen.add(name.casefold())
        package.extractall(str(destination))
    return destination / 'dsh-win7-portable'


def product_environment(portable, workspace):
    env = {key: value for key, value in os.environ.items() if key.upper() in (
        'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'SYSTEMDRIVE',
        'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS')}
    env['PATH'] = str(portable) + os.pathsep + str(Path(os.environ['SystemRoot']) / 'System32')
    env['DSH_HOME'] = str(workspace / 'home')
    env['DSH_TELEMETRY_MODE'] = 'DISABLED'
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--browser', help='Optional absolute Chromium executable, development observer only')
    parser.add_argument('--expected-commit', help='Require this exact clean product commit in archive provenance')
    args = parser.parse_args(argv)
    archive, output = Path(args.archive).resolve(), Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(result='failed', archive=str(archive), archiveSha256=digest(archive),
        scope='Actual extracted Portable on current Windows; Win7 and its browser are not certified; no remote model request.',
        inputSha256={name: digest(ROOT / 'scripts' / name) for name in (
            'verify_portable.py', 'portable_runtime_probe.py', 'portable_acp_probe.py', 'acp_permission_journey.py',
            'portable_browser_oracle.mjs', 'browser_onboarding.mjs', 'mcp_stdio_oracle.py',
            'oracles/mcp_stdio_python.py', 'oracles/mcp_stdio_peer.py')})
    node = shutil.which('node') if args.browser else None
    try:
        if args.browser and not node:
            raise RuntimeError('Development browser observer requires Node')
        with tempfile.TemporaryDirectory(prefix='dsh Portable 中文 ') as private:
            workspace = Path(private)
            portable = extract(archive, workspace)
            provenance = json.loads((portable / 'build-provenance.json').read_text(encoding='utf-8'))
            report['provenance'] = provenance
            if args.expected_commit and (provenance.get('product_commit') != args.expected_commit or provenance.get('worktree_dirty') is not False):
                raise RuntimeError('Portable does not come from the required clean product commit')
            for name, expected in provenance['python_runtime']['files'].items():
                if digest(portable / name) != expected:
                    raise RuntimeError('Extracted runtime hash mismatch: ' + name)
            for row in provenance['frontend']['files']:
                if digest(portable / row['path']) != row['sha256']:
                    raise RuntimeError('Extracted upstream frontend hash mismatch: ' + row['path'])
            report['frontendFilesChecked'] = len(provenance['frontend']['files'])
            env = product_environment(portable, workspace)
            result = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/portable_runtime_probe.py'), '--workspace', str(workspace)],
                cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=240)
            log = re.sub(r'token=[^\s]+', 'token=[redacted]', result.stdout + '\nSTDERR:\n' + result.stderr)
            output.with_suffix('.runtime.log').write_text(log, encoding='utf-8')
            if result.returncode:
                raise RuntimeError('Extracted runtime journey failed; see ' + str(output.with_suffix('.runtime.log')))
            messages = [json.loads(line[len('PORTABLE_PROBE '):]) for line in result.stdout.splitlines()
                        if line.startswith('PORTABLE_PROBE ')]
            if len(messages) != 1 or messages[0].get('result') != 'passed':
                raise RuntimeError('Missing successful extracted runtime report')
            report['runtime'] = messages[0]['value']
            report['runtimeStderr'] = result.stderr
            acp_workspace = workspace / 'acp-workspace'
            acp_workspace.mkdir()
            acp_environment = product_environment(portable, acp_workspace)
            acp = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/portable_acp_probe.py'), '--root', str(portable), '--workspace', str(acp_workspace)],
                cwd=str(acp_workspace), env=acp_environment, capture_output=True, encoding='utf-8', timeout=60)
            output.with_suffix('.acp.log').write_text(acp.stdout + '\nSTDERR:\n' + acp.stderr, encoding='utf-8')
            if acp.returncode or acp.stderr:
                raise RuntimeError('Extracted ACP stdio journey failed; see ' + str(output.with_suffix('.acp.log')))
            acp_report = json.loads(acp.stdout)
            if acp_report.get('result') != 'passed' or len(acp_report.get('value', {}).get('steps', [])) != 9:
                raise RuntimeError('Missing extracted ACP stdio ownership observations')
            report['acp'] = acp_report['value']
            permission_workspace = workspace / 'permission-workspace'
            permission_workspace.mkdir()
            permission = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/acp_permission_journey.py'), '--root', str(portable), '--workspace', str(permission_workspace)],
                cwd=str(permission_workspace), env=product_environment(portable, permission_workspace),
                capture_output=True, encoding='utf-8', timeout=120)
            output.with_suffix('.permissions.log').write_text(permission.stdout + '\nSTDERR:\n' + permission.stderr, encoding='utf-8')
            if permission.returncode or permission.stderr:
                raise RuntimeError('Extracted ACP permission journey failed; see ' + str(output.with_suffix('.permissions.log')))
            permission_report = json.loads(permission.stdout)
            if (permission_report.get('result') != 'passed' or permission_report.get('value', {}).get('processes') != 6
                    or permission_report.get('value', {}).get('modes') != ['allow', 'reject', 'malformed', 'cancel-late', 'close-late', 'eof']):
                raise RuntimeError('Missing extracted ACP permission ownership observations')
            report['acpPermissions'] = permission_report['value']
            mcp_report_path = workspace / 'mcp-stdio.json'
            mcp = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/mcp_stdio_python.py'), str(mcp_report_path),
                '--root', str(portable), '--consumer'], cwd=str(workspace),
                env=product_environment(portable, workspace), capture_output=True, encoding='utf-8', timeout=120)
            output.with_suffix('.mcp.log').write_text(mcp.stdout + '\nSTDERR:\n' + mcp.stderr, encoding='utf-8')
            if mcp.returncode or mcp.stderr or not mcp_report_path.exists():
                raise RuntimeError('Extracted MCP stdio journey failed; see ' + str(output.with_suffix('.mcp.log')))
            mcp_report = json.loads(mcp_report_path.read_text(encoding='utf-8'))
            validate_mcp_runtime(mcp_report)
            if mcp_report.get('root') != str(portable.resolve()):
                raise RuntimeError('Extracted MCP ownership or module provenance is incomplete')
            report['mcpStdio'] = mcp_report
            if args.browser:
                browser_report = output.with_suffix('.browser.json')
                # The observer launches the Host with the same restricted env.
                env_file = workspace / 'host-environment.json'
                env_file.write_text(json.dumps(env), encoding='utf-8')
                observed = subprocess.run([node, str(ROOT / 'scripts/portable_browser_oracle.mjs'),
                    '--python', str(portable / 'python.exe'), '--workspace', str(workspace),
                    '--environment', str(env_file), '--browser', str(Path(args.browser).resolve()),
                    '--output', str(browser_report)], cwd=str(workspace), capture_output=True,
                    encoding='utf-8', errors='replace', timeout=120)
                output.with_suffix('.browser.log').write_text(observed.stdout + '\nSTDERR:\n' + observed.stderr, encoding='utf-8')
                report['browser'] = json.loads(browser_report.read_text(encoding='utf-8')) if browser_report.is_file() else None
                if observed.returncode or not report['browser'] or not report['browser'].get('passed'):
                    raise RuntimeError('Extracted original-browser journey failed; see ' + str(browser_report))
            else:
                report['browser'] = dict(status='not-run')
            report['result'] = 'passed'
    except Exception as error:
        report['failure'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(result=report['result'], output=str(output), failure=report.get('failure'))))
    return 0 if report['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
