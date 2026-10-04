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
from scripts.mcp_http_oracle import validate_runtime_report as validate_mcp_http_runtime
from scripts.acp_mcp_oracle import validate_process as validate_acp_mcp_process
from scripts.subagent_acp_oracle import validate_process as validate_subagent_acp_process
from scripts.subagent_acp_teardown_oracle import validate_runtime as validate_subagent_acp_teardown
from scripts.mcp_disposal_oracle import validate_runtime as validate_mcp_disposal
from scripts.subprocess_ownership_oracle import validate_runtime as validate_subprocess_ownership
from scripts.oracles.subprocess_tree_python import observe as observe_subprocess_tree
from scripts.subprocess_tree_oracle import validate_observations as validate_subprocess_tree
from scripts.projection_cache_failure_oracle import validate_runtime as validate_projection_cache_reads
from scripts.session_observation_read_oracle import validate_runtime as validate_session_observation_reads
from scripts.session_corpus_list_oracle import validate_runtime as validate_session_corpus_list
from scripts.session_corpus_read_oracle import validate_runtime as validate_session_corpus_read
from scripts.session_lineage_oracle import validate_runtime as validate_session_lineage
from scripts.session_event_trace_oracle import validate_runtime as validate_session_event_trace
from scripts.session_filters_oracle import validate_runtime as validate_session_filters
from scripts.session_requests_oracle import validate_runtime as validate_session_requests
from scripts.webserver_reset_probe import validate as validate_webserver_reset
from scripts.python_directory_probe import validate as validate_python_directory
from scripts.session_snapshots_oracle import validate_runtime as validate_session_snapshots
from scripts.query_schema_oracle import validate_runtime as validate_query_schema
from scripts.query_engine_oracle import validate_runtime as validate_query_engine
from scripts.query_unicode_oracle import validate_runtime as validate_query_unicode, source_identity as unicode_source_identity
from scripts.session_text_oracle import validate_runtime as validate_session_text, source_identity as text_source_identity
from scripts.session_tools_oracle import validate_runtime as validate_session_tools, source_identity as tools_source_identity
from scripts.sqlite_format_oracle import validate_runtime as validate_sqlite_format, source_identity as format_source_identity


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
    parser.add_argument('--unicode-source', help='Fresh paired Unicode source observations from the release gate')
    parser.add_argument('--text-source', help='Fresh paired Session text source observations from the release gate')
    parser.add_argument('--text-inputs', help='The exact generated inputs used by the paired Session text observer')
    parser.add_argument('--tools-source', help='Fresh paired optional Session tool source observations from the release gate')
    parser.add_argument('--format-source', help='Fresh actual schema-19 format Source observations')
    parser.add_argument('--format-inputs', help='Exact schema-19 format generated inputs')
    args = parser.parse_args(argv)
    archive, output = Path(args.archive).resolve(), Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(result='failed', archive=str(archive), archiveSha256=digest(archive),
        scope='Actual extracted Portable on current Windows; Win7 and its browser are not certified; no remote model request.',
        inputSha256={name: digest(ROOT / 'scripts' / name) for name in (
            'verify_portable.py', 'portable_runtime_probe.py', 'portable_acp_probe.py', 'acp_permission_journey.py',
            'portable_browser_oracle.mjs', 'browser_onboarding.mjs', 'mcp_stdio_oracle.py',
            'oracles/mcp_stdio_python.py', 'oracles/mcp_stdio_peer.py', 'mcp_http_oracle.py',
            'oracles/mcp_http_python.py', 'oracles/mcp_http_peer.py', 'oracles/mcp_http_expected.json',
            'acp_mcp_oracle.py', 'acp_mcp_journey.py', 'subagent_acp_oracle.py',
            'subagent_acp_journey.py', 'oracles/subagent_acp_python.py',
            'subagent_acp_teardown_oracle.py', 'oracles/subagent_acp_teardown_python.py',
            'mcp_disposal_oracle.py', 'oracles/mcp_disposal_python.py',
            'subprocess_ownership_oracle.py', 'oracles/subprocess_ownership_python.py',
            'oracles/subagent_acp_peer.py', 'subprocess_tree_oracle.py', 'oracles/subprocess_tree_python.py',
            'oracles/subprocess_tree_peer.py', 'oracles/subprocess_host_exit_python.py',
            'projection_cache_failure_oracle.py', 'oracles/projection_cache_failure_python.py',
            'session_observation_read_oracle.py', 'oracles/session_observation_read_python.py',
            'oracles/session_observation_read_expected.json', 'session_corpus_list_oracle.py',
            'oracles/session_corpus_list_python.py', 'oracles/session_corpus_list_expected.json',
            'session_corpus_read_oracle.py', 'oracles/session_corpus_read_python.py', 'oracles/session_corpus_read_expected.json',
            'session_lineage_oracle.py', 'oracles/session_lineage_python.py', 'oracles/session_lineage_expected.json',
            'session_event_trace_oracle.py', 'oracles/session_event_trace_python.py',
            'oracles/session_event_trace_expected.json', 'oracles/session_event_trace_fixture.json',
            'session_filters_oracle.py', 'oracles/session_filters_python.py',
            'oracles/session_filters_expected.json', 'oracles/session_filters_cases.json',
            'session_requests_oracle.py', 'oracles/session_requests_python.py',
            'oracles/session_requests_expected.json', 'oracles/session_requests_cases.json', 'webserver_reset_probe.py',
            'session_snapshots_oracle.py', 'oracles/session_snapshots_python.py', 'oracles/session_snapshots_expected.json',
            'oracles/session_snapshot_fixture.py',
            'python_directory_probe.py', 'query_schema_oracle.py', 'oracles/query_schema_python.py',
            'oracles/query_schema_expected.json', 'query_engine_oracle.py', 'oracles/query_engine_python.py',
            'oracles/query_engine_expected.json', 'query_unicode_oracle.py', 'oracles/query_unicode_python.py',
            'oracles/query_unicode.probe.spec.ts', 'oracles/vitest.query-unicode-probe.config.mts',
            'session_text_oracle.py', 'oracles/session_text_python.py', 'oracles/session_text_inputs.py',
            'oracles/session_text.probe.spec.ts', 'oracles/vitest.session-text-probe.config.mts',
            'session_tools_oracle.py', 'oracles/session_tools_python.py', 'oracles/session_tools.probe.spec.ts',
            'oracles/vitest.session-tools-probe.config.mts', 'sqlite_format_oracle.py', 'oracles/sqlite_format_python.py',
            'oracles/sqlite_format_inputs.py', 'oracles/sqlite_format.probe.spec.ts', 'oracles/vitest.sqlite-format-probe.config.mts')})
    node = shutil.which('node') if args.browser else None
    try:
        if args.browser and not node:
            raise RuntimeError('Development browser observer requires Node')
        if args.unicode_source:
            unicode_source = Path(args.unicode_source).resolve()
        else:
            paired_path = output.with_suffix('.query-unicode-paired.json')
            paired = subprocess.run([sys.executable, str(ROOT / 'scripts/query_unicode_oracle.py'),
                                     '--output', str(paired_path)], capture_output=True, timeout=120)
            output.with_suffix('.query-unicode-source.log').write_bytes(paired.stdout + paired.stderr)
            if paired.returncode:
                raise RuntimeError('Fresh Unicode source qualification failed')
            unicode_source = paired_path.with_name(paired_path.stem + '.source.json')
        unicode_digest, unicode_locale = unicode_source_identity(json.loads(unicode_source.read_text(encoding='utf-8')))
        report['unicodeSourceSha256'] = digest(unicode_source)
        if args.text_source or args.text_inputs:
            if not args.text_source or not args.text_inputs:
                raise RuntimeError('Both Session text source and inputs are required')
            text_source, text_inputs = Path(args.text_source).resolve(), Path(args.text_inputs).resolve()
        else:
            paired_path = output.with_suffix('.session-text-paired.json')
            paired = subprocess.run([sys.executable, str(ROOT / 'scripts/session_text_oracle.py'),
                                     '--output', str(paired_path)], capture_output=True, timeout=150)
            output.with_suffix('.session-text-source.log').write_bytes(paired.stdout + paired.stderr)
            if paired.returncode:
                raise RuntimeError('Fresh Session text source qualification failed')
            text_source = paired_path.with_name(paired_path.stem + '.source.json')
            text_inputs = paired_path.with_name(paired_path.stem + '.inputs.json')
        text_digest, text_locale = text_source_identity(json.loads(text_source.read_text(encoding='utf-8')))
        report['sessionTextSourceSha256'] = digest(text_source)
        report['sessionTextInputSha256'] = digest(text_inputs)
        if args.tools_source:
            tools_source = Path(args.tools_source).resolve()
        else:
            paired_path = output.with_suffix('.session-tools-paired.json')
            paired = subprocess.run([sys.executable, str(ROOT / 'scripts/session_tools_oracle.py'), '--output', str(paired_path)],
                                    capture_output=True, timeout=150)
            output.with_suffix('.session-tools-source.log').write_bytes(paired.stdout + paired.stderr)
            if paired.returncode:
                raise RuntimeError('Fresh optional Session tool source qualification failed')
            tools_source = paired_path.with_name(paired_path.stem + '.source.json')
        tools_digest = tools_source_identity(json.loads(tools_source.read_text(encoding='utf-8')))
        report['sessionToolsSourceSha256'] = digest(tools_source)
        if args.format_source or args.format_inputs:
            if not args.format_source or not args.format_inputs:
                raise RuntimeError('Both SQLite format Source and inputs are required')
            format_source, format_inputs = Path(args.format_source).resolve(), Path(args.format_inputs).resolve()
        else:
            paired_path = output.with_suffix('.sqlite-format-paired.json')
            paired = subprocess.run([sys.executable, str(ROOT / 'scripts/sqlite_format_oracle.py'), '--output', str(paired_path)],
                                    capture_output=True, timeout=150)
            output.with_suffix('.sqlite-format-source.log').write_bytes(paired.stdout + paired.stderr)
            if paired.returncode:
                raise RuntimeError('Fresh SQLite format Source qualification failed')
            format_source = paired_path.with_name(paired_path.stem + '.source.json')
            format_inputs = paired_path.with_name(paired_path.stem + '.inputs.json')
        format_digest, format_frames = format_source_identity(json.loads(format_source.read_text(encoding='utf-8')))
        report['sqliteFormatSourceSha256'] = digest(format_source)
        report['sqliteFormatInputSha256'] = digest(format_inputs)
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
            http_report_path = workspace / 'mcp-http.json'
            http = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/mcp_http_python.py'), str(http_report_path), str(portable)],
                cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.http.log').write_text(http.stdout + '\nSTDERR:\n' + http.stderr, encoding='utf-8')
            if http.returncode or http.stderr or not http_report_path.exists():
                raise RuntimeError('Extracted MCP HTTP journey failed; see ' + str(output.with_suffix('.http.log')))
            http_report = json.loads(http_report_path.read_text(encoding='utf-8'))
            validate_mcp_http_runtime(http_report)
            if http_report.get('root') != str(portable.resolve()):
                raise RuntimeError('Extracted MCP HTTP module provenance is incomplete')
            report['mcpHttp'] = http_report
            acp_mcp_workspace = workspace / 'acp-mcp-consumer'
            acp_mcp = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/acp_mcp_journey.py'), '--root', str(portable), '--workspace', str(acp_mcp_workspace)],
                cwd=str(workspace), env=product_environment(portable, workspace),
                capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.acp-mcp.log').write_text(acp_mcp.stdout + '\nSTDERR:\n' + acp_mcp.stderr, encoding='utf-8')
            if acp_mcp.returncode or acp_mcp.stderr:
                raise RuntimeError('Extracted ACP MCP consumer failed; see ' + str(output.with_suffix('.acp-mcp.log')))
            acp_mcp_report = json.loads(acp_mcp.stdout)
            if acp_mcp_report.get('result') != 'passed':
                raise RuntimeError('Extracted ACP MCP consumer did not pass')
            validate_acp_mcp_process(acp_mcp_report.get('value'))
            report['acpMcp'] = acp_mcp_report['value']
            subagent_workspace = workspace / 'subagent-acp-consumer'
            subagent = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/subagent_acp_journey.py'), '--root', str(portable), '--workspace', str(subagent_workspace)],
                cwd=str(workspace), env=product_environment(portable, workspace),
                capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.subagent-acp.log').write_text(subagent.stdout + '\nSTDERR:\n' + subagent.stderr, encoding='utf-8')
            if subagent.returncode or subagent.stderr:
                raise RuntimeError('Extracted subprocess ACP consumer failed; see ' + str(output.with_suffix('.subagent-acp.log')))
            subagent_report = json.loads(subagent.stdout)
            if subagent_report.get('result') != 'passed':
                raise RuntimeError('Extracted subprocess ACP consumer did not pass')
            validate_subagent_acp_process(subagent_report.get('value'))
            report['subagentAcp'] = subagent_report['value']
            teardown_workspace = workspace / 'subagent-acp-teardown'
            teardown_workspace.mkdir()
            teardown_path = workspace / 'subagent-acp-teardown.json'
            teardown = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/subagent_acp_teardown_python.py'), str(teardown_workspace), str(teardown_path), '--root', str(portable)],
                cwd=str(workspace), env=product_environment(portable, workspace),
                capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.subagent-acp-teardown.log').write_text(teardown.stdout + '\nSTDERR:\n' + teardown.stderr, encoding='utf-8')
            if teardown.returncode or teardown.stderr or not teardown_path.is_file():
                raise RuntimeError('Extracted subprocess ACP teardown failed; see ' + str(output.with_suffix('.subagent-acp-teardown.log')))
            teardown_report = json.loads(teardown_path.read_text(encoding='utf-8'))
            validate_subagent_acp_teardown(teardown_report)
            if teardown_report['root'] != str(portable.resolve()):
                raise RuntimeError('Extracted subprocess ACP teardown module provenance differs')
            report['subagentAcpTeardown'] = teardown_report
            disposal_path = workspace / 'mcp-disposal.json'
            disposal = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/mcp_disposal_python.py'), str(disposal_path), '--root', str(portable)],
                cwd=str(workspace), env=product_environment(portable, workspace),
                capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.mcp-disposal.log').write_text(disposal.stdout + '\nSTDERR:\n' + disposal.stderr, encoding='utf-8')
            if disposal.returncode or disposal.stderr:
                raise RuntimeError('Extracted MCP disposal failed; see ' + str(output.with_suffix('.mcp-disposal.log')))
            disposal_report = json.loads(disposal_path.read_text(encoding='utf-8'))
            validate_mcp_disposal(disposal_report)
            if disposal_report['root'] != str(portable):
                raise RuntimeError('Extracted MCP disposal imported a different product')
            report['mcpDisposal'] = disposal_report
            ownership_path = workspace / 'subprocess-ownership.json'
            ownership = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/subprocess_ownership_python.py'), str(ownership_path), '--root', str(portable)],
                cwd=str(workspace), env=product_environment(portable, workspace),
                capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.subprocess-ownership.log').write_text(ownership.stdout + '\nSTDERR:\n' + ownership.stderr, encoding='utf-8')
            if ownership.returncode or ownership.stderr:
                raise RuntimeError('Extracted subprocess ownership failed; see ' + str(output.with_suffix('.subprocess-ownership.log')))
            ownership_report = json.loads(ownership_path.read_text(encoding='utf-8'))
            validate_subprocess_ownership(ownership_report)
            if ownership_report['root'] != str(portable):
                raise RuntimeError('Extracted subprocess ownership imported a different product')
            report['subprocessOwnership'] = ownership_report
            tree_report = observe_subprocess_tree(portable, str(portable / 'python.exe'), environment=env)
            validate_subprocess_tree(tree_report, portable)
            report['subprocessTree'] = tree_report
            cache_workspace = workspace / 'projection-cache-reads'
            cache_workspace.mkdir()
            cache_path = workspace / 'projection-cache-reads.json'
            cache_reads = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/projection_cache_failure_python.py'), str(cache_workspace), str(cache_path), '--root', str(portable)],
                cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.projection-cache-reads.log').write_text(cache_reads.stdout + '\nSTDERR:\n' + cache_reads.stderr, encoding='utf-8')
            if cache_reads.returncode or cache_reads.stderr or not cache_path.is_file():
                raise RuntimeError('Extracted projection cache reads failed; see ' + str(output.with_suffix('.projection-cache-reads.log')))
            cache_report = json.loads(cache_path.read_text(encoding='utf-8'))
            validate_projection_cache_reads(cache_report)
            if cache_report['root'] != str(portable):
                raise RuntimeError('Extracted projection cache reads imported a different product')
            report['projectionCacheReads'] = cache_report
            observation_path = workspace / 'session-observation-reads.json'
            observation_reads = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/session_observation_read_python.py'), str(observation_path), '--root', str(portable)],
                cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.session-observation-reads.log').write_text(observation_reads.stdout + '\nSTDERR:\n' + observation_reads.stderr, encoding='utf-8')
            if observation_reads.returncode or observation_reads.stderr or not observation_path.is_file():
                raise RuntimeError('Extracted Session observation reads failed; see ' + str(output.with_suffix('.session-observation-reads.log')))
            observation_report = json.loads(observation_path.read_text(encoding='utf-8'))
            validate_session_observation_reads(observation_report)
            if observation_report['root'] != str(portable):
                raise RuntimeError('Extracted Session observation reads imported a different product')
            report['sessionObservationReads'] = observation_report
            corpus_path = workspace / 'session-corpus-list.json'
            corpus_reads = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/session_corpus_list_python.py'), str(corpus_path), '--root', str(portable)],
                cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.session-corpus-list.log').write_text(corpus_reads.stdout + '\nSTDERR:\n' + corpus_reads.stderr, encoding='utf-8')
            if corpus_reads.returncode or corpus_reads.stderr or not corpus_path.is_file():
                raise RuntimeError('Extracted Session corpus listing failed; see ' + str(output.with_suffix('.session-corpus-list.log')))
            corpus_report = json.loads(corpus_path.read_text(encoding='utf-8'))
            validate_session_corpus_list(corpus_report)
            if corpus_report['root'] != str(portable):
                raise RuntimeError('Extracted Session corpus listing imported a different product')
            report['sessionCorpusList'] = corpus_report
            corpus_read_path = workspace / 'session-corpus-read.json'
            corpus_read = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/session_corpus_read_python.py'), str(corpus_read_path), '--root', str(portable)],
                cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.session-corpus-read.log').write_text(corpus_read.stdout + '\nSTDERR:\n' + corpus_read.stderr, encoding='utf-8')
            if corpus_read.returncode or corpus_read.stderr or not corpus_read_path.is_file():
                raise RuntimeError('Extracted Session corpus reads failed; see ' + str(output.with_suffix('.session-corpus-read.log')))
            corpus_read_report = json.loads(corpus_read_path.read_text(encoding='utf-8'))
            validate_session_corpus_read(corpus_read_report)
            if corpus_read_report['root'] != str(portable):
                raise RuntimeError('Extracted Session corpus reads imported a different product')
            report['sessionCorpusRead'] = corpus_read_report
            format_path = workspace / 'sqlite-format.json'
            format_result = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/oracles/sqlite_format_python.py'), str(format_path), '--root', str(portable),
                '--inputs', str(format_inputs), '--source', str(format_source)], cwd=str(workspace), env=env,
                capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.sqlite-format.log').write_text(format_result.stdout + '\nSTDERR:\n' + format_result.stderr, encoding='utf-8')
            if format_result.returncode or format_result.stderr or not format_path.is_file():
                raise RuntimeError('Extracted SQLite format failed')
            report['sqliteFormat'] = json.loads(format_path.read_text(encoding='utf-8'))
            validate_sqlite_format(report['sqliteFormat'], portable, format_digest, format_frames)
            for name, key, validate in [('session_lineage', 'sessionLineage', validate_session_lineage),
                                        ('session_event_trace', 'sessionEventTrace', validate_session_event_trace),
                                        ('session_filters', 'sessionFilters', validate_session_filters),
                                        ('session_requests', 'sessionRequests', validate_session_requests),
                                        ('session_snapshots', 'sessionSnapshots', validate_session_snapshots),
                                        ('query_schema', 'querySchema', validate_query_schema),
                                        ('query_engine', 'queryEngine', validate_query_engine),
                                        ('query_unicode', 'queryUnicode', lambda value: validate_query_unicode(
                                            value, portable, unicode_digest, unicode_locale)),
                                        ('session_text', 'sessionText', lambda value: validate_session_text(
                                            value, portable, text_digest, text_locale)),
                                        ('session_tools', 'sessionTools', lambda value: validate_session_tools(value, portable, tools_digest))]:
                trace_path = workspace / (name + '.json')
                trace_command = [str(portable / 'python.exe'), '-I', '-u',
                    str(ROOT / 'scripts/oracles' / (name + '_python.py')), str(trace_path), '--root', str(portable)]
                if name == 'session_text':
                    trace_command += ['--inputs', str(text_inputs)]
                trace = subprocess.run(trace_command,
                    cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
                output.with_suffix('.' + name + '.log').write_text(trace.stdout + '\nSTDERR:\n' + trace.stderr, encoding='utf-8')
                if trace.returncode or trace.stderr or not trace_path.is_file():
                    raise RuntimeError('Extracted ' + name + ' failed')
                trace_report = json.loads(trace_path.read_text(encoding='utf-8'))
                validate(trace_report)
                if trace_report['root'] != str(portable):
                    raise RuntimeError('Extracted ' + name + ' imported a different product')
                report[key] = trace_report
            directory_path = workspace / 'python-directory.json'
            directory = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/python_directory_probe.py'), '--root', str(portable), '--output', str(directory_path)],
                cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.python-directory.log').write_text(directory.stdout + '\nSTDERR:\n' + directory.stderr, encoding='utf-8')
            if directory.returncode or directory.stderr or not directory_path.is_file():
                raise RuntimeError('Extracted Python directory publication failed')
            directory_report = json.loads(directory_path.read_text(encoding='utf-8'))
            validate_python_directory(directory_report)
            if directory_report['root'] != str(portable):
                raise RuntimeError('Extracted Python directory publication imported a different product')
            report['pythonDirectory'] = directory_report
            reset_path = workspace / 'webserver-reset.json'
            reset = subprocess.run([str(portable / 'python.exe'), '-I', '-u',
                str(ROOT / 'scripts/webserver_reset_probe.py'), '--root', str(portable), '--output', str(reset_path)],
                cwd=str(workspace), env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
            output.with_suffix('.webserver-reset.log').write_text(reset.stdout + '\nSTDERR:\n' + reset.stderr, encoding='utf-8')
            if reset.returncode or reset.stderr or not reset_path.is_file():
                raise RuntimeError('Extracted WebServer reset cleanup failed')
            reset_report = json.loads(reset_path.read_text(encoding='utf-8'))
            validate_webserver_reset(reset_report, portable)
            report['webServerReset'] = reset_report
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
