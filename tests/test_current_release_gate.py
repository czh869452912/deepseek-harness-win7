import argparse
import copy
import importlib.util
import json
import functools
import subprocess
import sys
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from scripts.mcp_stdio_oracle import MODES as MCP_MODES, expected_row as mcp_expected_row
from scripts.mcp_http_oracle import EXPECTED as HTTP_EXPECTED
from scripts.subagent_acp_oracle import expected_process as expected_subagent_acp_process
from scripts.subagent_acp_teardown_oracle import expected as expected_subagent_acp_teardown
from scripts.subprocess_tree_oracle import expected as expected_subprocess_tree
from scripts.mcp_disposal_oracle import expected as expected_mcp_disposal
from scripts.subprocess_ownership_oracle import expected as expected_subprocess_ownership
from scripts.projection_cache_failure_oracle import expected as expected_projection_cache_reads
from scripts.session_observation_read_oracle import expected as expected_session_observation_reads
from scripts.session_corpus_list_oracle import expected as expected_session_corpus_list
from scripts.session_corpus_read_oracle import expected as expected_session_corpus_read
from scripts.session_lineage_oracle import expected as expected_session_lineage
from scripts.session_event_trace_oracle import expected as expected_session_event_trace
from scripts.session_filters_oracle import expected as expected_session_filters
from scripts.session_requests_oracle import expected as expected_session_requests
from scripts.session_snapshots_oracle import expected as expected_session_snapshots
from scripts.python_directory_probe import EXPECTED as expected_python_directory
from scripts.query_schema_oracle import expected as expected_query_schema
from scripts.query_engine_oracle import expected as expected_query_engine
from scripts.query_unicode_oracle import observation_digest
from scripts.session_text_oracle import observation_digest as text_observation_digest
from scripts.session_tools_oracle import observation_digest as tools_observation_digest
from scripts.sqlite_format_oracle import observation_digest as format_observation_digest
from scripts.sqlite_provider_oracle import observation_digest as provider_observation_digest
from scripts.jsonl_provider_oracle import observation_digest as jsonl_observation_digest
from scripts.tool_scheduler_oracle import identity as scheduler_observation_digest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('current_release_gate', ROOT / 'scripts/verify_release.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def regression_xml(path, omit=None, skip=None, duplicate=None, failure=None):
    suites = ET.Element('testsuites')
    suite = ET.SubElement(suites, 'testsuite')
    for module, names in GATE.REQUIRED_REGRESSION.items():
        for name in sorted(names):
            key = (module, name)
            if key == omit:
                continue
            case = ET.SubElement(suite, 'testcase', classname='tests.' + module, name=name)
            if key == skip:
                ET.SubElement(case, 'skipped', message='optional lane')
            if key == failure:
                ET.SubElement(case, 'failure', message='actual failure')
            if key == duplicate:
                ET.SubElement(suite, 'testcase', classname='tests.' + module, name=name)
    optional = ET.SubElement(suite, 'testcase', classname='tests.test_posix', name='not_for_windows')
    ET.SubElement(optional, 'skipped', message='platform semantics')
    ET.ElementTree(suites).write(str(path), encoding='utf-8')


@pytest.mark.parametrize('module', ['test_subprocess_tree_source', 'test_subprocess_physical_tree',
    'test_subagent_acp_peer_encoding'])
@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_physical_tree_and_utf8_peer_lanes_cannot_be_optional(tmp_path, module, damage):
    path = tmp_path / 'pytest.xml'
    key = (module, sorted(GATE.REQUIRED_REGRESSION[module])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'tail', 'root-alive', 'descendant-alive',
    'wrong-exit', 'foreign-runtime', 'missing-live-barrier', 'missing-physical-identities'])
def test_extracted_physical_tree_is_required_and_cannot_hide_survivors(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['subprocessTree']
    elif damage == 'tail':
        report['subprocessTree'].pop()
    else:
        row = report['subprocessTree'][0]
        if damage == 'root-alive':
            row['observed']['after']['root'] = True
        elif damage == 'descendant-alive':
            row['observed']['after']['descendant'] = True
        elif damage == 'wrong-exit':
            row['observed']['exitCode'] = 0
        elif damage == 'foreign-runtime':
            row['product']['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
        elif damage == 'missing-live-barrier':
            del row['observed']['before']
        else:
            del row['physical']
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_projection_cache_read_source_lane_cannot_be_optional(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    module = 'test_projection_cache_failure_source'
    key = (module, sorted(GATE.REQUIRED_REGRESSION[module])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'tail', 'duplicate', 'reorder', 'cold-error',
    'error-identity', 'cold-overwrite', 'cold-replay', 'prepared-error', 'prepared-overwrite',
    'tail-apply', 'snapshot-cut', 'foreign-root', 'foreign-module', 'python', 'unknown-field'])
def test_extracted_projection_cache_reads_cannot_hide_failure_or_change_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    cache = report['projectionCacheReads']
    rows = cache['observations']
    if damage == 'missing':
        del report['projectionCacheReads']
    elif damage == 'tail':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'cold-error':
        del rows[0]['observed']['error']
    elif damage == 'error-identity':
        rows[0]['observed']['error']['sameParserFailure'] = False
    elif damage == 'cold-overwrite':
        rows[0]['observed']['document']['record']['rows']['controlled/count']['val'] = 2
    elif damage == 'cold-replay':
        rows[0]['observed']['applied'] = [0, 1]
    elif damage == 'prepared-error':
        rows[1]['observed']['error'] = copy.deepcopy(rows[0]['observed']['error'])
    elif damage == 'prepared-overwrite':
        rows[1]['observed']['document']['record']['rows']['controlled/count']['seq'] = 1
    elif damage == 'tail-apply':
        rows[2]['observed']['applied'] = []
    elif damage == 'snapshot-cut':
        rows[2]['observed']['snapshot']['asOfSeq'] = 0
    elif damage == 'foreign-root':
        cache['root'] = str(tmp_path / 'foreign')
        cache['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'foreign-module':
        cache['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        cache['python'] = [3, 9, 0]
    else:
        cache['unknown'] = True
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_session_observation_read_source_lane_cannot_be_optional(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    module = 'test_session_observation_read_source'
    key = (module, sorted(GATE.REQUIRED_REGRESSION[module])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'tail', 'duplicate', 'reorder', 'message', 'cause',
    'raw-failure', 'missing-release', 'double-release', 'early-release', 'live-borrow',
    'cursor', 'foreign-root', 'foreign-module', 'python', 'unknown-field'])
def test_extracted_session_observation_reads_require_exact_errors_cut_and_release(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    read = report['sessionObservationReads']
    rows = read['observations']
    if damage == 'missing':
        del report['sessionObservationReads']
    elif damage == 'tail':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'message':
        rows[0]['observed']['error']['message'] = 'session not found: owned'
    elif damage == 'cause':
        rows[4]['observed']['error']['sameCause'] = False
    elif damage == 'raw-failure':
        rows[9]['observed']['error']['sameFailure'] = False
    elif damage == 'missing-release':
        rows[8]['observed']['counters']['releases'] = 0
    elif damage == 'double-release':
        rows[9]['observed']['counters']['releases'] = 2
    elif damage == 'early-release':
        rows[10]['observed']['releasesAfterFirst'] = 1
    elif damage == 'live-borrow':
        rows[11]['observed']['counters']['borrows'] = 1
    elif damage == 'cursor':
        rows[15]['observed']['cut']['cursor'] = 0
    elif damage == 'foreign-root':
        read['root'] = str(tmp_path / 'foreign')
        read['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'foreign-module':
        read['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        read['python'] = [3, 9, 0]
    else:
        read['unknown'] = True
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_session_corpus_list_source_lane_cannot_be_optional(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    module = 'test_session_corpus_list_source'
    key = (module, sorted(GATE.REQUIRED_REGRESSION[module])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'tail', 'duplicate', 'reorder', 'message', 'cause',
    'foreign-cause', 'abort-identity', 'signal', 'live-precedence', 'clone', 'weak-count',
    'foreign-root', 'foreign-module', 'python', 'unknown-field'])
def test_extracted_session_corpus_list_requires_exact_errors_signals_and_sources(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    read = report['sessionCorpusList']
    rows = read['observations']
    if damage == 'missing':
        del report['sessionCorpusList']
    elif damage == 'tail':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'message':
        rows[4]['observed']['error']['message'] = 'session source headers conflict'
    elif damage == 'cause':
        rows[5]['observed']['error']['sameCause'] = False
    elif damage == 'foreign-cause':
        rows[6]['observed']['error']['sameCause'] = False
    elif damage == 'abort-identity':
        rows[8]['observed']['error']['sameFailure'] = False
    elif damage == 'signal':
        rows[9]['observed']['counters']['sameSignal'] = False
    elif damage == 'live-precedence':
        rows[1]['observed']['records'][0]['live'] = False
    elif damage == 'clone':
        rows[11]['observed']['originalCwd'] = '/mutated'
    elif damage == 'weak-count':
        rows[0]['observed']['counters']['lists'] = False
    elif damage == 'foreign-root':
        read['root'] = str(tmp_path / 'foreign')
        read['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'foreign-module':
        read['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        read['python'] = [3, 9, 0]
    else:
        read['unknown'] = True
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('operation', ['add', 'upgrade'])
@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_zip_staging_real_sharing_lane_cannot_be_optional(tmp_path, operation, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_python_plugin_zip_staging',
           'test_wrapped_zip_needs_no_post_extraction_subroot_rename[' + operation + ']')
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_session_corpus_read_source_lane_cannot_be_optional(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    module = 'test_session_corpus_read_source'
    key = (module, sorted(GATE.REQUIRED_REGRESSION[module])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'tail', 'duplicate', 'reorder', 'message', 'cause',
    'foreign-cause', 'signal', 'peak', 'early-settlement', 'queued-after-abort', 'projection-order',
    'clone', 'title-mutable', 'foreign-root', 'foreign-module', 'python', 'unknown-field'])
def test_extracted_session_corpus_read_requires_exact_sources_and_batch_drain(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    read = report['sessionCorpusRead']
    rows = read['observations']
    by_name = {row['name']: row['observed'] for row in rows}
    if damage == 'missing':
        del report['sessionCorpusRead']
    elif damage == 'tail':
        rows.pop()
    elif damage == 'duplicate':
        rows[-1] = copy.deepcopy(rows[0])
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'message':
        by_name['load-missing-record']['error']['message'] = 'session not found: a'
    elif damage == 'cause':
        by_name['load-failure']['error']['sameCause'] = False
    elif damage == 'foreign-cause':
        by_name['load-foreign-failure']['error']['sameCause'] = False
    elif damage == 'signal':
        by_name['batch-concurrency']['counters']['signals'] = False
    elif damage == 'peak':
        by_name['batch-concurrency']['counters']['peak'] = 3
    elif damage == 'early-settlement':
        by_name['batch-abort-drain']['settledBeforeDrain'] = True
    elif damage == 'queued-after-abort':
        by_name['batch-abort-drain']['counters']['inspections'].append('c')
    elif damage == 'projection-order':
        by_name['batch-concurrency']['projectBeforeNext'] = False
    elif damage == 'clone':
        by_name['load-cold']['detached'] = False
    elif damage == 'title-mutable':
        by_name['batch-clone']['titleMutationRefused'] = False
    elif damage == 'foreign-root':
        read['root'] = str(tmp_path / 'foreign')
        read['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'foreign-module':
        read['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        read['python'] = [3, 9, 0]
    else:
        read['unknown'] = True
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


def test_regression_requires_browser_portable_and_acp_process_lanes(tmp_path):
    path = tmp_path / 'pytest.xml'
    regression_xml(path)
    assert GATE.validate_regression(path) == {'required_lanes': 452, 'skipped': 1}


@pytest.mark.parametrize('module', ['test_native_web_browser', 'test_portable_smoke', 'test_acp_stdio_journey', 'test_acp_permission_process', 'test_mcp_stdio_transport', 'test_mcp_supervisor', 'test_mcp_schema', 'test_mcp_config', 'test_mcp_tools_source', 'test_mcp_image_consumer', 'test_mcp_http_source', 'test_mcp_http_transport', 'test_mcp_supervisor_source', 'test_mcp_factory_source', 'test_acp_mcp_source', 'test_acp_mcp_runtime_source', 'test_acp_mcp_abort_source', 'test_acp_mcp_process', 'test_acp_mcp_runtime'])
@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_incomplete_regression_cannot_certify_a_release(tmp_path, module, damage):
    path = tmp_path / 'pytest.xml'
    name = sorted(GATE.REQUIRED_REGRESSION[module])[0]
    regression_xml(path, **{damage: (module, name)})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


def test_environment_removes_inherited_credentials_without_modifying_the_parent(monkeypatch, tmp_path):
    for name in ('DEEPSEEK_API_KEY', 'openai_api_key', 'ANTHROPIC_ACCESS_TOKEN', 'DSH_HOME', 'PYTHONPATH'):
        monkeypatch.setenv(name, 'not-a-real-secret')
    browser = tmp_path / 'chromium.exe'
    environment = GATE.release_environment(browser)
    assert environment['DSH_TEST_CHROMIUM'] == str(browser)
    assert not set(environment).intersection({'DEEPSEEK_API_KEY', 'openai_api_key', 'ANTHROPIC_ACCESS_TOKEN', 'DSH_HOME', 'PYTHONPATH'})
    assert GATE.os.environ['DEEPSEEK_API_KEY'] == 'not-a-real-secret'


@pytest.mark.parametrize('report', [
    {'status': 'different'}, {'passed': False},
    {'cases': 18, 'matched': 17, 'mismatches': ['different']},
    {'status': 'passed', 'cases': []}, {'status': 'matched', 'passed': False},
    {'status': 'passed', 'mismatches': ['different']},
])
def test_failed_paired_receipt_is_rejected(tmp_path, report):
    path = tmp_path / 'paired.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_paired(path)


@pytest.mark.parametrize('report', [
    {'status': 'matched', 'cases': [{'status': 'matched'}]},
    {'status': 'passed', 'cases': [{'status': 'reviewed-upstream-bug'}]},
    {'passed': True}, {'cases': 18, 'matched': 18, 'mismatches': []},
])
def test_successful_paired_receipt_forms_are_supported(tmp_path, report):
    path = tmp_path / 'paired.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    assert GATE.validate_paired(path) == report


@functools.lru_cache(maxsize=1)
def unicode_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='unicode-validator-fixture-') as directory:
        output = Path(directory) / 'native.json'
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/oracles/query_unicode_python.py'),
                                 str(output)], capture_output=True, timeout=90)
        assert result.returncode == 0 and not result.stderr, result.stderr
        return json.loads(output.read_text(encoding='utf-8'))


@functools.lru_cache(maxsize=1)
def session_text_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='text-validator-fixture-') as directory:
        output, inputs = Path(directory) / 'native.json', Path(directory) / 'inputs.json'
        generated = subprocess.run([sys.executable, str(ROOT / 'scripts/oracles/session_text_inputs.py'),
                                    '--output', str(inputs)], capture_output=True, timeout=90)
        assert generated.returncode == 0 and not generated.stderr, generated.stderr
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/oracles/session_text_python.py'),
                                 str(output), '--inputs', str(inputs)], capture_output=True, timeout=90)
        assert result.returncode == 0 and not result.stderr, result.stderr
        return json.loads(output.read_text(encoding='utf-8')), GATE.digest(inputs)


@functools.lru_cache(maxsize=1)
def scheduler_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='scheduler-validator-fixture-') as directory:
        output = Path(directory) / 'native.json'
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/oracles/tool_scheduler_python.py'),
                                 '--root', str(ROOT), '--output', str(output)], capture_output=True, timeout=45)
        assert result.returncode == 0 and not result.stderr, result.stderr
        return json.loads(output.read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'modules-missing',
                                   'module-changed', 'foreign-root', 'missing-observation'])
def test_extracted_scheduler_requires_fresh_source_and_owned_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['toolScheduler']
    elif damage == 'source-missing':
        del candidate['tool_scheduler_observations_sha256']
    elif damage == 'source-changed':
        candidate['tool_scheduler_observations_sha256'] = '0' * 64
    elif damage == 'modules-missing':
        del candidate['tool_scheduler_modules']
    elif damage == 'module-changed':
        report['toolScheduler']['modules']['dsh/core/tool_calls.py'] = '0' * 64
    elif damage == 'foreign-root':
        report['toolScheduler']['root'] = str(tmp_path.parent)
    else:
        report['toolScheduler']['rows'].pop()
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='toolScheduler'):
        GATE.validate_extracted(path, archive, candidate)


def extracted_receipt(tmp_path):
    archive = tmp_path / 'portable.zip'
    archive.write_bytes(b'exact candidate archive')
    candidate = {'product_commit': 'a' * 40, 'worktree_dirty': False}
    scheduler = copy.deepcopy(scheduler_runtime_fixture())
    scheduler['root'] = str(tmp_path)
    candidate['tool_scheduler_observations_sha256'] = scheduler_observation_digest(scheduler['rows'])
    candidate['tool_scheduler_modules'] = scheduler['modules'].copy()
    report = {'result': 'passed', 'browser': {'passed': True}, 'runtime': {'checks': ['actual runtime']},
              'acp': {'processes': 2, 'steps': ['initialize-0', 'invalid-params-before-effects',
                  'persistent-new', 'close-list-0', 'eof-0', 'initialize-1',
                  'new-process-resume-no-history-updates', 'close-list-1', 'eof-1']},
              'runtimeStderr': '', 'frontendFilesChecked': 119, 'archive': str(archive),
              'archiveSha256': GATE.digest(archive), 'provenance': dict(candidate), 'toolScheduler': scheduler}
    modes = ['allow', 'reject', 'malformed', 'cancel-late', 'close-late', 'eof']
    report['acpPermissions'] = {'processes': 6, 'modes': modes, 'observations': [
        {'mode': mode, 'executed': mode == 'allow', 'modelRequests': 2 if mode in modes[:3] else 1, 'stderr': [''],
         'audit': [{'type': 'approval/asked', 'data': {'id': 'owned'}}, {'type': 'approval/decided', 'data': {
             'id': 'owned', 'outcome': {'allow': 'allowed-once', 'reject': 'rejected', 'malformed': 'unavailable'}.get(mode, 'cancelled')}}]}
        for mode in modes]}
    report['mcpStdio'] = {'observations': [mcp_expected_row(mode) for mode in MCP_MODES],
        'consumer': {'registered': True, 'output': 'controlled consumer', 'retired': True, 'childExited': True, 'pending': 0},
        'python': '3.8.10 controlled fixture', 'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py')}
    report['mcpHttp'] = {'observations': copy.deepcopy(HTTP_EXPECTED['observations']),
        'consumer': {'registered': True, 'output': 'controlled consumer', 'retired': True, 'closed': True,
            'writers': 0, 'tasks': 0, 'pending': 0, 'childExited': True},
        'python': '3.8.10 controlled fixture', 'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py')}
    report['acpMcp'] = {'stdioProcesses': 3, 'stdioCalls': 3, 'stdioReaped': True,
        'httpCalls': 1, 'httpClosed': True, 'acpClosed': True, 'modelRequests': 8,
        'scope': 'Actual canonical ACP process, stdio/HTTP consumers and same-session resume; no external endpoint.'}
    report['subprocessTree'] = expected_subprocess_tree()
    for row in report['subprocessTree']:
        row['physical'] = {'host': 100, 'root': 101, 'descendant': 102, 'cwd': str(tmp_path)}
        row['product'] = {'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['subagentAcp'] = expected_subagent_acp_process()
    teardown_rows = copy.deepcopy(expected_subagent_acp_teardown(tmp_path))
    for row in teardown_rows:
        row['observed']['records'] = [{'spawn': {'pid': 123, 'cwd': str(tmp_path)}}] + row['observed'].pop('wire')
    report['subagentAcpTeardown'] = {'observations': teardown_rows, 'root': str(tmp_path),
        'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['mcpDisposal'] = dict(expected_mcp_disposal(), root=str(tmp_path),
        module=str(tmp_path / 'dsh/__init__.py'), python=[3, 8, 10])
    report['subprocessOwnership'] = {'observations': expected_subprocess_ownership(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['projectionCacheReads'] = {'observations': expected_projection_cache_reads(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['sessionObservationReads'] = {'observations': expected_session_observation_reads(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['sessionCorpusList'] = {'observations': expected_session_corpus_list(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['sessionCorpusRead'] = {'observations': expected_session_corpus_read(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['sessionLineage'] = {'observations': expected_session_lineage(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['sessionEventTrace'] = {'observations': expected_session_event_trace(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    report['sessionFilters'] = {'observations': expected_session_filters(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3,8,10]}
    report['sessionRequests'] = {'observations': expected_session_requests(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3,8,10]}
    report['sessionSnapshots'] = {'observations': expected_session_snapshots(),
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3,8,10]}
    report['querySchema'] = dict(root=str(tmp_path), module=str(tmp_path / 'dsh/__init__.py'), python=[3,8,10],
        observations=expected_query_schema(), sqlite=dict(version='3.51.2',
            sourceId='2026-01-09 17:27:48 b270f8339eb13b504d0b2ba154ebca966b7dde08e40c3ed7d559749818cb2075',
            dll=str(tmp_path / 'dsh/session/bin/sqlite3.dll'),
            sha256='2339b9e7c8b2d4be67d5516fed37aa70c02bdb463386c47ab130d00586751642'))
    report['pythonDirectory'] = dict(root=str(tmp_path), module=str(tmp_path / 'dsh/boot/python_directory_mutation.py'),
        python='3.8.10', platform='win32', observations=copy.deepcopy(expected_python_directory))
    manifest = json.loads((ROOT / 'dsh/session/bin/sqlite3.json').read_text(encoding='utf-8'))
    report['queryEngine'] = dict(root=str(tmp_path), moduleFile=str(tmp_path / 'dsh/session/query_engine.py'),
        python='3.8.10', sqliteVersion=manifest['version'], sqliteSourceId=manifest['source_id'],
        sqliteDllSha256=manifest['dll_sha256'], manifest=manifest, observations=expected_query_engine())
    unicode = copy.deepcopy(unicode_runtime_fixture())
    unicode['root'] = str(tmp_path)
    unicode['moduleFile'] = str(tmp_path / 'dsh/session/icu_collation.py')
    for library in unicode['runtime']['libraries']:
        library['path'] = str(tmp_path / 'dsh/session/bin/icu' / library['name'])
    report['queryUnicode'] = unicode
    candidate['query_unicode_observations_sha256'] = observation_digest(unicode['observations'])
    candidate['query_unicode_locale'] = unicode['runtime']['locale']
    text, inputs_digest = copy.deepcopy(session_text_runtime_fixture())
    text['root'] = str(tmp_path)
    text['moduleFile'] = str(tmp_path / 'dsh/session/text.py')
    for library in text['runtime']['libraries']:
        library['path'] = str(tmp_path / 'dsh/session/bin/icu' / library['name'])
    report['sessionText'] = text
    report['sessionTextInputSha256'] = inputs_digest
    candidate['session_text_observations_sha256'] = text_observation_digest(text['observations'])
    candidate['session_text_locale'] = text['runtime']['locale']
    candidate['session_text_inputs_sha256'] = inputs_digest
    tools = copy.deepcopy(session_tools_runtime_fixture())
    tools['root'] = str(tmp_path)
    tools['moduleFile'] = str(tmp_path / 'dsh/session/tool_query.py')
    report['sessionTools'] = tools
    candidate['session_tools_observations_sha256'] = tools_observation_digest(tools['rows'])
    candidate['session_tools_modules'] = tools['modules'].copy()
    format_report, format_inputs_digest = copy.deepcopy(sqlite_format_runtime_fixture())
    format_report['root'] = str(tmp_path)
    format_report['moduleFile'] = str(tmp_path / 'dsh/session/sqlite_codec.py')
    format_report['libraryFile'] = str(tmp_path / 'dsh/session/bin/zstd/dsh_zstd.dll')
    report['sqliteFormat'] = format_report
    report['sqliteFormatInputSha256'] = format_inputs_digest
    candidate['sqlite_format_observations_sha256'] = format_observation_digest(format_report['rows'])
    candidate['sqlite_format_frames_sha256'] = format_report['frameInputsSha256']
    candidate['sqlite_format_inputs_sha256'] = format_inputs_digest
    candidate['sqlite_format_modules'] = format_report['modules'].copy()
    candidate['sqlite_format_assets'] = format_report['assets'].copy()
    provider, provider_inputs_digest = copy.deepcopy(sqlite_provider_runtime_fixture())
    provider['root'] = str(tmp_path)
    provider['moduleFile'] = str(tmp_path / 'dsh/session/sqlite_store.py')
    report['sqliteProvider'] = provider
    candidate['sqlite_provider_observations_sha256'] = provider_observation_digest(provider['rows'])
    candidate['sqlite_provider_inputs_sha256'] = provider_inputs_digest
    candidate['sqlite_provider_modules'] = provider['modules'].copy()
    candidate['sqlite_provider_assets'] = provider['assets'].copy()
    jsonl, jsonl_inputs_digest = copy.deepcopy(jsonl_provider_runtime_fixture())
    jsonl['root'] = str(tmp_path)
    jsonl['moduleFile'] = str(tmp_path / 'dsh/session/jsonl_store.py')
    report['jsonlProvider'] = jsonl
    candidate['jsonl_provider_observations_sha256'] = jsonl_observation_digest(jsonl['rows'])
    candidate['jsonl_provider_inputs_sha256'] = jsonl_inputs_digest
    candidate['jsonl_provider_modules'] = jsonl['modules'].copy()
    candidate['jsonl_provider_assets'] = jsonl['assets'].copy()
    report['webServerReset'] = dict(root=str(tmp_path), module=str(tmp_path / 'dsh/host/webserver/socket_server.py'),
        python='3.8.10', platform='win32', observations=[
            dict(mode='http-stream', resets=3, owned=True, alive=True, retired=True, errors=[]),
            dict(mode='upgrade', resets=3, owned=True, alive=True, retired=True, errors=[])])
    return archive, candidate, report


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_session_text_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_session_text', 'test_session_text_source'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'text-regression.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def jsonl_provider_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='jsonl-provider-validator-fixture-') as directory:
        output = Path(directory) / 'paired.json'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/jsonl_provider_oracle.py'), '--output', str(output)],
            capture_output=True, timeout=150)
        assert result.returncode == 0 and not result.stderr, result.stderr
        paired = json.loads(output.read_text(encoding='utf-8'))
        native = json.loads(output.with_name('paired.native.json').read_text(encoding='utf-8'))
        return native, paired['generatedInputsSha256']


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_jsonl_provider_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_jsonl_canonical', 'test_jsonl_provider_source', 'test_jsonl_metadata_boundaries'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'jsonl-regression.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['receipt', 'root', 'moduleFile', 'python', 'modules', 'assets', 'rows', 'input', 'source', 'module-source', 'asset-source'])
def test_extracted_jsonl_provider_requires_fresh_source_and_owned_resources(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    current = report['jsonlProvider']
    if damage == 'receipt':
        del report['jsonlProvider']
    elif damage in ('root', 'moduleFile', 'python'):
        current[damage] = 'different'
    elif damage in ('modules', 'assets'):
        current[damage].pop(next(iter(current[damage])))
    elif damage == 'rows':
        current['rows'].pop()
    elif damage == 'input':
        candidate['jsonl_provider_inputs_sha256'] = '0' * 64
    elif damage == 'source':
        candidate['jsonl_provider_observations_sha256'] = '0' * 64
    elif damage == 'module-source':
        candidate['jsonl_provider_modules'] = None
    else:
        candidate['jsonl_provider_assets'] = None
    output = tmp_path / 'jsonl-extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='jsonlProvider'):
        GATE.validate_extracted(output, archive, candidate)


@functools.lru_cache(maxsize=1)
def sqlite_provider_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='sqlite-provider-validator-fixture-') as directory:
        output = Path(directory) / 'paired.json'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/sqlite_provider_oracle.py'), '--output', str(output)],
                                capture_output=True, timeout=150)
        assert result.returncode == 0 and not result.stderr, result.stderr
        paired = json.loads(output.read_text(encoding='utf-8'))
        native = json.loads(output.with_name('paired.native.json').read_text(encoding='utf-8'))
        return native, paired['generatedInputsSha256']


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_sqlite_provider_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_sqlite_canonical', 'test_sqlite_provider_source', 'test_sqlite_remote'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'provider-regression.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'runtime', 'hash', 'asset', 'inventory', 'value',
                                  'digest', 'inputs', 'null-digest', 'null-modules', 'null-assets'])
def test_extracted_sqlite_provider_requires_fresh_source_and_owned_resources(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    current = report['sqliteProvider']
    if damage == 'missing':
        del report['sqliteProvider']
    elif damage == 'root':
        current['root'] = str(tmp_path / 'foreign')
    elif damage == 'module':
        current['moduleFile'] = 'foreign'
    elif damage == 'runtime':
        current['python'] = '3.9.0'
    elif damage == 'hash':
        current['modules']['dsh/session/sqlite_store.py'] = '0' * 64
    elif damage == 'asset':
        current['assets']['dsh/session/resources/sql/schema.sql'] = '0' * 64
    elif damage == 'inventory':
        current['rows'].pop()
    elif damage == 'value':
        current['rows'][0]['value'] = False
    elif damage == 'digest':
        candidate['sqlite_provider_observations_sha256'] = '0' * 64
    elif damage == 'inputs':
        candidate['sqlite_provider_inputs_sha256'] = '0' * 64
    elif damage == 'null-digest':
        candidate['sqlite_provider_observations_sha256'] = None
    elif damage == 'null-modules':
        candidate['sqlite_provider_modules'] = None
    else:
        candidate['sqlite_provider_assets'] = None
    output = tmp_path / 'provider-extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sqliteProvider'):
        GATE.validate_extracted(output, archive, candidate)


@functools.lru_cache(maxsize=1)
def sqlite_format_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='sqlite-format-validator-fixture-') as directory:
        output = Path(directory) / 'paired.json'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/sqlite_format_oracle.py'), '--output', str(output)],
                                capture_output=True, timeout=150)
        assert result.returncode == 0 and not result.stderr, result.stderr
        paired = json.loads(output.read_text(encoding='utf-8'))
        native = json.loads(output.with_name('paired.native.json').read_text(encoding='utf-8'))
        return native, paired['generatedInputsSha256']


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_sqlite_format_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_sqlite_format', 'test_sqlite_format_source'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'format-regression.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'library', 'runtime', 'hash', 'asset', 'inventory', 'value',
                                  'digest', 'frames', 'inputs', 'null-digest', 'null-modules', 'null-assets', 'missing-frames', 'version'])
def test_extracted_sqlite_format_requires_fresh_source_and_owned_assets(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    current = report['sqliteFormat']
    if damage == 'missing':
        del report['sqliteFormat']
    elif damage == 'root':
        current['root'] = str(tmp_path / 'foreign')
    elif damage == 'module':
        current['moduleFile'] = 'foreign'
    elif damage == 'library':
        current['libraryFile'] = 'foreign'
    elif damage == 'runtime':
        current['python'] = '3.9.0'
    elif damage == 'hash':
        current['modules']['dsh/session/sqlite_codec.py'] = '0' * 64
    elif damage == 'asset':
        current['assets']['zstd-dictionary.bin'] = '0' * 64
    elif damage == 'inventory':
        current['rows'].pop()
    elif damage == 'value':
        current['rows'][0]['value'] = 'foreign'
    elif damage == 'digest':
        candidate['sqlite_format_observations_sha256'] = '0' * 64
    elif damage == 'frames':
        candidate['sqlite_format_frames_sha256'] = '0' * 64
    elif damage == 'inputs':
        report['sqliteFormatInputSha256'] = '0' * 64
    elif damage == 'null-digest':
        candidate['sqlite_format_observations_sha256'] = None
    elif damage == 'null-modules':
        candidate['sqlite_format_modules'] = None
    elif damage == 'null-assets':
        candidate['sqlite_format_assets'] = None
    elif damage == 'missing-frames':
        del candidate['sqlite_format_frames_sha256']
    else:
        current['zstdVersion'] = 'foreign'
    output = tmp_path / 'format-extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sqliteFormat'):
        GATE.validate_extracted(output, archive, candidate)


@functools.lru_cache(maxsize=1)
def session_tools_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='session-tools-validator-fixture-') as directory:
        output = Path(directory) / 'native.json'
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/oracles/session_tools_python.py'), str(output)],
                                capture_output=True, timeout=90)
        assert result.returncode == 0 and not result.stderr, result.stderr
        return json.loads(output.read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_optional_session_tool_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_session_tools', 'test_session_tools_source', 'test_session_tools_profile'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'tools-regression.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'runtime', 'hash', 'inventory', 'value', 'digest', 'candidate', 'null-digest', 'null-modules'])
def test_extracted_session_tools_require_fresh_source_and_owned_modules(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    tools = report['sessionTools']
    if damage == 'missing':
        del report['sessionTools']
    elif damage == 'root':
        tools['root'] = str(tmp_path / 'foreign')
    elif damage == 'module':
        tools['moduleFile'] = 'foreign'
    elif damage == 'runtime':
        tools['python'] = '3.9.0'
    elif damage == 'hash':
        tools['modules']['dsh/session/tool_query.py'] = '0' * 64
    elif damage == 'inventory':
        tools['rows'].pop()
    elif damage == 'value':
        tools['rows'][0]['value'] = 'foreign'
    elif damage == 'digest':
        candidate['session_tools_observations_sha256'] = '0' * 64
    elif damage == 'null-digest':
        candidate['session_tools_observations_sha256'] = None
    elif damage == 'null-modules':
        candidate['session_tools_modules'] = None
    else:
        del candidate['session_tools_modules']
    output = tmp_path / 'tools-extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sessionTools'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'data', 'locale', 'normalization',
                                   'comparison', 'extraction', 'order', 'digest', 'inputs', 'candidate', 'null-inputs'])
def test_extracted_session_text_requires_exact_source_and_owned_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    text = report['sessionText']
    if damage == 'missing':
        del report['sessionText']
    elif damage == 'root':
        text['root'] = str(tmp_path / 'foreign')
    elif damage == 'module':
        text['moduleFile'] = str(tmp_path / 'foreign/provider.py')
    elif damage == 'data':
        text['unicodeDataSha256'] = '0' * 64
    elif damage == 'locale':
        text['runtime']['locale'] = 'foreign'
    elif damage == 'normalization':
        text['runtime']['normalization'] = 16
    elif damage == 'comparison':
        text['observations']['cases'][0]['matched'] = False
    elif damage == 'extraction':
        text['observations']['events'][0] = 'foreign'
    elif damage == 'order':
        text['observations']['orders'][0]['listed'].reverse()
    elif damage == 'digest':
        candidate['session_text_observations_sha256'] = '0' * 64
    elif damage == 'inputs':
        report['sessionTextInputSha256'] = '0' * 64
    elif damage == 'null-inputs':
        candidate['session_text_inputs_sha256'] = None
        del report['sessionTextInputSha256']
    else:
        del candidate['session_text_observations_sha256']
    output = tmp_path / 'text-extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sessionText'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_unicode_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_query_unicode', 'test_query_unicode_source'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'unicode-regression.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'library', 'locale', 'normalization',
                                   'comparison', 'fingerprint', 'digest', 'candidate'])
def test_extracted_unicode_requires_exact_source_and_owned_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    unicode = report['queryUnicode']
    if damage == 'missing':
        del report['queryUnicode']
    elif damage == 'root':
        unicode['root'] = str(tmp_path / 'foreign')
    elif damage == 'module':
        unicode['moduleFile'] = str(tmp_path / 'foreign/provider.py')
    elif damage == 'library':
        unicode['runtime']['libraries'][0]['sha256'] = '0' * 64
    elif damage == 'locale':
        unicode['runtime']['locale'] = 'foreign'
    elif damage == 'normalization':
        unicode['runtime']['normalization'] = 16
    elif damage == 'comparison':
        unicode['observations']['comparisons'][0][2] = 1
    elif damage == 'fingerprint':
        unicode['observations']['fingerprints'][0]['fingerprint'] = 'foreign'
    elif damage == 'digest':
        candidate['query_unicode_observations_sha256'] = '0' * 64
    else:
        del candidate['query_unicode_observations_sha256']
    output = tmp_path / 'unicode-extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='queryUnicode'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_query_engine_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_query_engine', 'test_query_engine_source', 'test_session_remote'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'regression.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'root', 'module', 'runtime', 'sqlite', 'source', 'dll', 'manifest', 'observations'])
def test_extracted_query_engine_requires_candidate_provider_and_exact_observations(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    engine = report['queryEngine']
    if damage == 'missing':
        del report['queryEngine']
    elif damage == 'root':
        engine['root'] = str(tmp_path / 'foreign')
        engine['moduleFile'] = str(tmp_path / 'foreign/dsh/session/query_engine.py')
    elif damage == 'module':
        engine['moduleFile'] = str(tmp_path / 'foreign/provider.py')
    elif damage == 'runtime':
        engine['python'] = '3.9.0'
    elif damage == 'sqlite':
        engine['sqliteVersion'] = '3.35.5'
    elif damage == 'source':
        engine['sqliteSourceId'] = 'foreign'
    elif damage == 'dll':
        engine['sqliteDllSha256'] = '0' * 64
    elif damage == 'manifest':
        engine['manifest'] = {}
    else:
        engine['observations'] = []
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='queryEngine'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_query_schema_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_sqlite_database', 'test_query_schema', 'test_query_schema_source', 'test_session_windows_dll_loading'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'pytest.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'tail', 'strict', 'foreign-write', 'generation',
    'foreign-root', 'foreign-module', 'version', 'source-id', 'dll', 'hash', 'unknown'])
def test_extracted_query_schema_requires_candidate_database_and_exact_observations(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    schema = report['querySchema']
    if damage == 'missing':
        del report['querySchema']
    elif damage == 'tail':
        schema['observations'].pop()
    elif damage in ('strict', 'foreign-write', 'generation'):
        indexed = {row['name']: row['observed'] for row in schema['observations']}
        if damage == 'strict':
            indexed['memory-schema']['strict'][0]['strict'] = 0
        elif damage == 'foreign-write':
            indexed['foreign-app']['unchanged'] = False
        else:
            indexed['upgrade']['generation'] = 7
    elif damage == 'foreign-root':
        schema['root'] = str(tmp_path / 'foreign')
    elif damage == 'foreign-module':
        schema['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'unknown':
        schema['unknown'] = True
    else:
        key = {'version': 'version', 'source-id': 'sourceId', 'dll': 'dll', 'hash': 'sha256'}[damage]
        schema['sqlite'][key] = 'foreign'
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='querySchema'):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_python_directory_publication_lanes_are_mandatory(tmp_path, damage):
    for name in GATE.REQUIRED_REGRESSION['test_python_directory_mutation']:
        path = tmp_path / 'pytest.xml'
        regression_xml(path, **{damage: ('test_python_directory_mutation', name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'tail', 'reverse', 'unknown', 'publication', 'recovery',
    'journal', 'foreign-root', 'foreign-module', 'python', 'platform'])
def test_extracted_python_directory_publication_is_exact_and_owned(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    directory = report['pythonDirectory']
    if damage == 'missing':
        del report['pythonDirectory']
    elif damage == 'tail':
        directory['observations'].pop()
    elif damage == 'reverse':
        directory['observations'].reverse()
    elif damage == 'unknown':
        directory['unknown'] = True
    elif damage == 'publication':
        directory['observations'][0]['published'] = False
    elif damage == 'recovery':
        directory['observations'][2]['recovered'] = False
    elif damage == 'journal':
        directory['observations'][3]['completeJournal'] = False
    elif damage == 'foreign-root':
        directory['root'] = str(tmp_path / 'foreign')
    elif damage == 'foreign-module':
        directory['module'] = str(tmp_path / 'foreign/dsh/boot/python_directory_mutation.py')
    elif damage == 'python':
        directory['python'] = '3.9.0'
    else:
        directory['platform'] = 'linux'
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='pythonDirectory'):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_webserver_reset_lanes_are_mandatory(tmp_path, damage):
    for name in GATE.REQUIRED_REGRESSION['test_webserver_peer_reset']:
        path = tmp_path / 'pytest.xml'
        regression_xml(path, **{damage: ('test_webserver_peer_reset', name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_mux_write_lifetime_lanes_are_mandatory(tmp_path, damage):
    for name in GATE.REQUIRED_REGRESSION['test_gateway_mux_write_lifetime']:
        path = tmp_path / 'pytest.xml'
        regression_xml(path, **{damage: ('test_gateway_mux_write_lifetime', name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_session_snapshot_lanes_are_mandatory(tmp_path, damage):
    for module in ('test_session_snapshots_source', 'test_session_snapshots'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            path = tmp_path / 'pytest.xml'
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'tail', 'reverse', 'incarnation', 'revision',
    'change-time', 'foreign-root', 'foreign-module', 'python', 'unknown'])
def test_extracted_session_snapshots_are_exact_and_owned(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    snapshot = report['sessionSnapshots']
    if damage == 'missing':
        del report['sessionSnapshots']
    elif damage == 'tail':
        snapshot['observations'].pop()
    elif damage == 'reverse':
        snapshot['observations'].reverse()
    elif damage in ('incarnation', 'revision', 'change-time'):
        indexed = {row['name']: row['observed'] for row in snapshot['observations']}
        if damage == 'incarnation':
            indexed['sqlite-copy']['different'] = False
        elif damage == 'revision':
            indexed['sqlite-append']['counterDelta'] = 2
        else:
            indexed['jsonl-restored-stat']['changeFieldAdvanced'] = False
    elif damage == 'foreign-root':
        snapshot['root'] = str(tmp_path / 'foreign')
    elif damage == 'foreign-module':
        snapshot['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        snapshot['python'] = [3, 9, 0]
    else:
        snapshot['unknown'] = True
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sessionSnapshots'):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['missing', 'empty', 'reverse', 'tail', 'reset-count',
    'survivor', 'not-owned', 'host-error', 'foreign-root', 'foreign-module', 'python', 'platform', 'unknown', 'numeric-boolean'])
def test_extracted_webserver_reset_cannot_hide_failure_or_change_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    reset = report['webServerReset']
    if damage == 'missing':
        del report['webServerReset']
    elif damage == 'empty':
        reset['observations'] = []
    elif damage == 'reverse':
        reset['observations'].reverse()
    elif damage == 'tail':
        reset['observations'].pop()
    elif damage == 'reset-count':
        reset['observations'][0]['resets'] = 2
    elif damage == 'survivor':
        reset['observations'][0]['retired'] = False
    elif damage == 'not-owned':
        reset['observations'][1]['owned'] = False
    elif damage == 'host-error':
        reset['observations'][0]['errors'] = ['reset escaped']
    elif damage == 'numeric-boolean':
        reset['observations'][0]['alive'] = 1
    elif damage == 'foreign-root':
        reset['root'] = str(tmp_path / 'foreign')
    elif damage == 'foreign-module':
        reset['module'] = str(tmp_path / 'foreign/dsh/host/webserver/socket_server.py')
    elif damage == 'python':
        reset['python'] = '3.9.0'
    elif damage == 'platform':
        reset['platform'] = 'linux'
    else:
        reset['unknown'] = True
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='WebServer reset cleanup'):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['browser-skipped', 'runtime-missing', 'runtime-stderr',
                                    'archive', 'commit', 'dirty', 'frontend', 'acp-missing', 'acp-tail',
                                    'permission-missing', 'permission-tail', 'permission-unsafe', 'permission-audit',
                                    'mcp-missing', 'mcp-tail', 'mcp-reaped', 'mcp-foreign-module',
                                    'mcp-child-alive', 'mcp-consumer-type', 'mcp-python', 'http-missing',
                                    'http-tail', 'http-child-alive', 'http-consumer-type', 'http-module'])
def test_extracted_runtime_and_browser_receipt_is_bound_to_the_candidate(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'browser-skipped':
        report['browser'] = {'status': 'not-run'}
    elif damage == 'runtime-missing':
        report['runtime'] = None
    elif damage == 'runtime-stderr':
        report['runtimeStderr'] = 'fatal diagnostic'
    elif damage == 'archive':
        report['archiveSha256'] = 'wrong'
    elif damage == 'commit':
        report['provenance']['product_commit'] = 'b' * 40
    elif damage == 'dirty':
        report['provenance']['worktree_dirty'] = True
    elif damage == 'acp-missing':
        del report['acp']
    elif damage == 'acp-tail':
        report['acp']['steps'].pop()
    elif damage == 'permission-missing':
        del report['acpPermissions']
    elif damage == 'permission-tail':
        report['acpPermissions']['observations'].pop()
    elif damage == 'permission-unsafe':
        report['acpPermissions']['observations'][2]['executed'] = True
    elif damage == 'permission-audit':
        report['acpPermissions']['observations'][0]['audit'][1]['data']['id'] = 'foreign'
    elif damage == 'mcp-missing':
        del report['mcpStdio']
    elif damage == 'mcp-tail':
        report['mcpStdio']['observations'].pop()
    elif damage == 'mcp-reaped':
        report['mcpStdio']['observations'][0]['reaped'] = False
    elif damage == 'mcp-foreign-module':
        report['mcpStdio']['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'mcp-child-alive':
        report['mcpStdio']['consumer']['childExited'] = False
    elif damage == 'mcp-consumer-type':
        report['mcpStdio']['consumer']['registered'] = 1
    elif damage == 'mcp-python':
        report['mcpStdio']['python'] = '3.8.100 controlled fixture'
    elif damage == 'http-missing':
        del report['mcpHttp']
    elif damage == 'http-tail':
        report['mcpHttp']['observations'].pop()
    elif damage == 'http-child-alive':
        report['mcpHttp']['consumer']['childExited'] = False
    elif damage == 'http-consumer-type':
        report['mcpHttp']['consumer']['registered'] = 1
    elif damage == 'http-module':
        report['mcpHttp']['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    else:
        report['frontendFilesChecked'] = 0
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


def test_clean_and_explicit_dirty_receipts_have_distinct_acceptance(tmp_path):
    archive, candidate, report = extracted_receipt(tmp_path)
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    assert GATE.validate_extracted(path, archive, candidate) == report
    candidate['worktree_dirty'] = report['provenance']['worktree_dirty'] = True
    path.write_text(json.dumps(report), encoding='utf-8')
    assert GATE.validate_extracted(path, archive, candidate) == report


def test_failure_replaces_previous_success_with_nonpublishable_diagnostics(tmp_path, monkeypatch):
    summary = tmp_path / 'summary.json'
    summary.write_text('{"result":"passed","publishable":true}', encoding='utf-8')
    def fail(args, output):
        assert not summary.exists()
        raise RuntimeError('required observer unavailable')
    monkeypatch.setattr(GATE, 'verify', fail)
    assert GATE.main(['--output-dir', str(tmp_path)]) == 1
    assert json.loads(summary.read_text(encoding='utf-8')) == {
        'result': 'failed', 'publishable': False, 'failure': 'required observer unavailable'}


def test_dirty_preview_is_never_a_publishable_success(tmp_path, monkeypatch):
    def preview(args, output):
        assert args.allow_dirty is True
        return {'result': 'development-preview', 'publishable': False}
    monkeypatch.setattr(GATE, 'verify', preview)
    assert GATE.main(['--allow-dirty', '--output-dir', str(tmp_path)]) == 0
    assert json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8'))['publishable'] is False


def test_default_gate_rejects_dirty_checkout_before_build(tmp_path, monkeypatch):
    browser = tmp_path / 'chromium.exe'
    browser.write_bytes(b'observer')
    (tmp_path / 'migration').mkdir()
    (tmp_path / 'migration/baseline.json').write_text(json.dumps({'target_upstream': 'b' * 40}), encoding='utf-8')
    monkeypatch.setattr(GATE, 'ROOT', tmp_path)
    monkeypatch.setattr(GATE.subprocess, 'check_output', lambda *args, **kwargs: 'v22.22.2\n')
    def git(*arguments, root=None):
        if arguments == ('rev-parse', 'HEAD'):
            return 'b' * 40 if root is not None else 'a' * 40
        return '' if root is not None else ' M dsh/core/agent.py'
    monkeypatch.setattr(GATE, 'git', git)
    with pytest.raises(RuntimeError, match='clean checkout'):
        GATE.verify(argparse.Namespace(browser=str(browser), allow_dirty=False, prepare=False), tmp_path)


def test_current_gate_includes_recent_contracts_and_only_uploads_receipt_archive():
    assert {'acp_sessions', 'acp_model_output', 'acp_stdio', 'acp_permissions', 'mcp_stdio', 'mcp_http', 'acp_mcp', 'subagent_acp', 'subagent_acp_teardown', 'mcp_disposal', 'subprocess_ownership'} <= set(GATE.PAIRED_DRIVERS)
    assert {'acp', 'acp-app', 'mcp', 'subagent-acp'} <= set(GATE.OFFICIAL_CONFIGS)
    assert {'deepseek', 'pi', 'compaction', 'approval', 'cordis_retirement', 'workflow_ralph', 'pruner'} <= set(GATE.PAIRED_DRIVERS)
    assert len(GATE.PAIRED_DRIVERS) == len(set(GATE.PAIRED_DRIVERS))
    workflow = (ROOT / '.github/workflows/verify.yml').read_text(encoding='utf-8')
    assert '--browser $browser' in workflow
    assert '${{ steps.gate.outputs.archive }}' in workflow
    assert 'archive_sha256' in workflow and 'publishable' in workflow


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_subprocess_ownership_source_lane_cannot_be_optional(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_subprocess_ownership_source', next(iter(GATE.REQUIRED_REGRESSION['test_subprocess_ownership_source'])))
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'pending-owner', 'fallback', 'aggregate', 'foreign-root', 'weak-python'])
def test_extracted_subprocess_ownership_preserves_pending_handles_and_failure_members(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    ownership = report['subprocessOwnership']
    if damage == 'missing':
        del report['subprocessOwnership']
    elif damage == 'pending-owner':
        ownership['observations'][1]['observed']['retained']['ordinary'] = 0
    elif damage == 'fallback':
        ownership['observations'][2]['observed']['trace'].pop()
    elif damage == 'aggregate':
        ownership['observations'][2]['observed']['error']['members'].pop()
    elif damage == 'foreign-root':
        ownership['root'] = str(tmp_path / 'foreign')
        ownership['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    else:
        ownership['python'] = ['3', '8', '10']
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['missing', 'numeric-reaped', 'no-stdio', 'missing-model-consumer', 'open-http', 'open-acp'])
def test_extracted_acp_mcp_consumer_cannot_be_omitted_or_fabricated(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['acpMcp']
    elif damage == 'numeric-reaped':
        report['acpMcp']['stdioReaped'] = 1
    elif damage == 'no-stdio':
        report['acpMcp']['stdioProcesses'] = 0
    elif damage == 'missing-model-consumer':
        report['acpMcp']['modelRequests'] = 7
    elif damage == 'open-http':
        report['acpMcp']['httpClosed'] = False
    else:
        report['acpMcp']['acpClosed'] = False
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


def test_node_setup_runs_each_locked_workspace_without_prefix_root_ambiguity(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(GATE.shutil, 'which', lambda name: 'npm.cmd')
    monkeypatch.setattr(GATE, 'run', lambda command, name, output, **kwargs: calls.append((command, kwargs)))
    GATE.prepare_node_dependencies(tmp_path, {'PATH': 'pinned-node'})
    assert [entry[1]['cwd'] for entry in calls] == [ROOT / 'scripts/oracles', ROOT / 'scripts/oracles/official']
    assert all(entry[0][0:2] == ['npm.cmd', 'ci'] and '--prefix' not in entry[0] for entry in calls)
    assert all(entry[1]['env'] == {'PATH': 'pinned-node'} for entry in calls)


@pytest.mark.parametrize('module', ['test_subagent_acp_source', 'test_agent_signal_source',
    'test_subagent_acp_process', 'test_subagent_acp_signal', 'test_subagent_acp_consumer', 'test_subagent_acp',
    'test_subagent_acp_teardown_source', 'test_subagent_acp_dispose_cancellation'])
@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_subprocess_acp_and_signal_lanes_cannot_be_optional(tmp_path, module, damage):
    path = tmp_path / 'pytest.xml'
    name = sorted(GATE.REQUIRED_REGRESSION[module])[0]
    regression_xml(path, **{damage: (module, name)})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'numeric-reaped', 'missing-child-model', 'missing-file',
    'parent-leak', 'open-parent'])
def test_extracted_subprocess_acp_consumer_cannot_be_omitted_or_fabricated(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['subagentAcp']
    elif damage == 'numeric-reaped':
        report['subagentAcp']['childReaped'] = 1
    elif damage == 'missing-child-model':
        report['subagentAcp']['childRequests'] = 0
    elif damage == 'missing-file':
        report['subagentAcp']['fileWork'] = False
    elif damage == 'parent-leak':
        report['subagentAcp']['parentContextIsolated'] = False
    else:
        report['subagentAcp']['parentClosed'] = False
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


def test_node_setup_refuses_missing_package_manager(tmp_path, monkeypatch):
    monkeypatch.setattr(GATE.shutil, 'which', lambda name: None)
    with pytest.raises(RuntimeError, match='pinned npm'):
        GATE.prepare_node_dependencies(tmp_path, {})


@pytest.mark.parametrize('damage', ['missing', 'empty', 'lost-cause', 'recreated-failure', 'lost-exit', 'foreign-module', 'foreign-root'])
def test_extracted_subprocess_acp_teardown_cannot_be_omitted_or_fabricated(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    teardown = report['subagentAcpTeardown']
    if damage == 'missing':
        del report['subagentAcpTeardown']
    elif damage == 'empty':
        teardown['observations'] = []
    elif damage == 'lost-cause':
        del teardown['observations'][0]['observed']['disposeFailure']['cause']
    elif damage == 'recreated-failure':
        teardown['observations'][0]['observed']['sameDisposeFailure'] = False
    elif damage == 'lost-exit':
        teardown['observations'][0]['observed']['actualExit'] = 0
    elif damage == 'foreign-module':
        teardown['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    else:
        teardown['root'] = str(tmp_path / 'foreign')
        teardown['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_mcp_disposal_source_lane_cannot_be_optional(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_mcp_disposal_source', next(iter(GATE.REQUIRED_REGRESSION['test_mcp_disposal_source'])))
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ['missing', 'swap', 'queued-fetch', 'warning', 'foreign-root', 'weak-python'])
def test_extracted_mcp_disposal_requires_queue_factory_and_runtime_ownership(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    disposal = report['mcpDisposal']
    if damage == 'missing':
        del report['mcpDisposal']
    elif damage == 'swap':
        disposal['supervisor'][2]['trace'] = disposal['supervisor'][2]['trace'][:-2]
    elif damage == 'queued-fetch':
        disposal['supervisor'][-1]['trace'].append(['fetch', 'tools/list'])
    elif damage == 'warning':
        disposal['factory']['logs'].pop()
    elif damage == 'foreign-root':
        disposal['root'] = str(tmp_path / 'foreign')
        disposal['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    else:
        disposal['python'] = ['3', '8', '10']
    path = tmp_path / 'receipt.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path, archive, candidate)


@pytest.mark.parametrize('module', ['test_session_lineage_source','test_session_event_trace_source',
    'test_session_lineage','test_session_event_trace'])
@pytest.mark.parametrize('damage', ['omit','skip','duplicate','failure'])
def test_session_tracing_required_lanes_cannot_be_optional(tmp_path,module,damage):
    for name in GATE.REQUIRED_REGRESSION[module]:
        path = tmp_path / 'pytest.xml'
        regression_xml(path, **{damage:(module,name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('key',['sessionLineage','sessionEventTrace'])
@pytest.mark.parametrize('damage',['missing','tail','duplicate','reorder','foreign-root','foreign-module','python','unknown'])
def test_extracted_session_tracing_requires_exact_observations_and_runtime(tmp_path,key,damage):
    archive,candidate,report = extracted_receipt(tmp_path)
    read = report[key]
    if damage == 'missing':
        del report[key]
    elif damage == 'tail':
        read['observations'].pop()
    elif damage == 'duplicate':
        read['observations'][-1] = copy.deepcopy(read['observations'][0])
    elif damage == 'reorder':
        read['observations'].reverse()
    elif damage == 'foreign-root':
        read['root'] = str(tmp_path / 'foreign')
        read['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'foreign-module':
        read['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'python':
        read['python'] = [3,9,0]
    else:
        read['unknown'] = True
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report),encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path,archive,candidate)

@pytest.mark.parametrize('module',['test_session_requests_source','test_session_sqlite_query_source','test_session_requests'])
@pytest.mark.parametrize('damage',['omit','skip','duplicate','failure'])
def test_search_request_required_lanes_cannot_be_optional(tmp_path,module,damage):
    for name in GATE.REQUIRED_REGRESSION[module]:
        path = tmp_path / 'pytest.xml'
        regression_xml(path,**{damage:(module,name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('damage',['missing','tail','duplicate','reorder','foreign-root','foreign-module','python','unknown','index-open','query-copy','sql-injection','snippet'])
def test_extracted_requests_require_exact_observations_and_runtime(tmp_path,damage):
    archive,candidate,report = extracted_receipt(tmp_path)
    read = report['sessionRequests']
    indexed = {row['name']:row['observed'] for row in read['observations']}
    if damage == 'missing':
        del report['sessionRequests']
    elif damage == 'tail':
        read['observations'].pop()
    elif damage == 'duplicate':
        read['observations'][-1] = copy.deepcopy(read['observations'][0])
    elif damage == 'reorder':
        read['observations'].reverse()
    elif damage == 'foreign-root':
        read['root'] = str(tmp_path/'foreign')
        read['module'] = str(tmp_path/'foreign/dsh/__init__.py')
    elif damage == 'foreign-module':
        read['module'] = str(tmp_path/'foreign/dsh/__init__.py')
    elif damage == 'python':
        read['python'] = [3,9,0]
    elif damage == 'index-open':
        indexed['invalid-public-limit']['opened'] = True
    elif damage == 'query-copy':
        indexed['owned-values']['value']['sessionFilters'][0]['values'][0] = 'foreign'
    elif damage == 'sql-injection':
        indexed['sql-injection-inert']['matches'] = ['a','b','c']
    elif damage == 'snippet':
        indexed['snippet-late-match-two']['value'] = '…f'
    else:
        read['unknown'] = True
    path = tmp_path/'extracted.json'
    path.write_text(json.dumps(report),encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path,archive,candidate)


@pytest.mark.parametrize('module',['test_session_filters_source','test_session_filters'])
@pytest.mark.parametrize('damage',['omit','skip','duplicate','failure'])
def test_session_filters_required_lanes_cannot_be_optional(tmp_path,module,damage):
    for name in GATE.REQUIRED_REGRESSION[module]:
        path = tmp_path / 'pytest.xml'
        regression_xml(path,**{damage:(module,name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('damage',['missing','tail','duplicate','reorder','foreign-root','foreign-module','python','unknown','early-copy','literal-matching'])
def test_extracted_filters_require_exact_observations_and_runtime(tmp_path,damage):
    archive,candidate,report = extracted_receipt(tmp_path)
    read = report['sessionFilters']
    indexed = {row['name']:row['observed'] for row in read['observations']}
    if damage == 'missing':
        del report['sessionFilters']
    elif damage == 'tail':
        read['observations'].pop()
    elif damage == 'duplicate':
        read['observations'][-1] = copy.deepcopy(read['observations'][0])
    elif damage == 'reorder':
        read['observations'].reverse()
    elif damage == 'foreign-root':
        read['root'] = str(tmp_path/'foreign')
        read['module'] = str(tmp_path/'foreign/dsh/__init__.py')
    elif damage == 'foreign-module':
        read['module'] = str(tmp_path/'foreign/dsh/__init__.py')
    elif damage == 'python':
        read['python'] = [3,9,0]
    elif damage == 'early-copy':
        indexed['public-sessions-before-await']['records'] = []
    elif damage == 'literal-matching':
        indexed['text-case-i']['matches'] = [True,True,True,True]
    else:
        read['unknown'] = True
    path = tmp_path/'extracted.json'
    path.write_text(json.dumps(report),encoding='utf-8')
    with pytest.raises(RuntimeError):
        GATE.validate_extracted(path,archive,candidate)
