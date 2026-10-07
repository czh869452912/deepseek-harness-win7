import argparse
import copy
import hashlib
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
from scripts.http_redirect_oracle import identity as redirect_observation_digest
from scripts.javascript_workflow_oracle import observation_digest as javascript_observation_digest
from scripts.runtime_context_oracle import observation_digest as context_observation_digest
from scripts.javascript_ready_oracle import observation_digest as ready_observation_digest
from scripts.javascript_initial_oracle import observation_digest as initial_observation_digest
from scripts.session_number_oracle import observation_digest as number_observation_digest
from scripts.session_diagnostic_oracle import observation_digest as diagnostic_observation_digest
from scripts.session_restore_sign_oracle import observation_digest as restore_sign_observation_digest
from scripts.runtime_full_request_oracle import observation_digest as full_request_observation_digest
from scripts.deepseek_error_oracle import observation_digest as deepseek_error_observation_digest
from test_deepseek_error_consumers import damage_observations
from scripts.deepseek_capture_oracle import observation_digest as deepseek_capture_observation_digest
from test_deepseek_capture_consumers import damage_observations as damage_capture_observations
from scripts.persistence_read_oracle import observation_digest as read_observation_digest
from scripts.llm_prepared_oracle import observation_digest as llm_prepared_observation_digest
from test_llm_prepared_consumers import damage_observations as damage_llm_prepared_observations
from scripts.llm_config_oracle import observation_digest as llm_config_observation_digest
from test_llm_config_consumers import damage_observations as damage_llm_config_observations
from test_win32_stat_consumers import damage_runtime as damage_win32_stat_runtime
from test_sdk_profile_consumers import damage_runtime as damage_sdk_profile_runtime
from scripts.sdk_profile_cases import EXTRACTED_DAMAGES as SDK_EXTRACTED_DAMAGES
from scripts.permission_presets_cases import damage_runtime as damage_permission_runtime, damage_source as damage_permission_source
from scripts.tool_errors_cases import damage_runtime as damage_tool_error_runtime
from scripts.tool_durable_cases import damage_runtime as damage_tool_durable_runtime
from scripts.agent_dependencies_cases import damage_runtime as damage_agent_dependencies_runtime
from scripts.tool_errors_oracle import OBSERVER_INPUTS as TOOL_ERROR_OBSERVER_INPUTS
from scripts.tool_durable_oracle import OBSERVER_INPUTS as TOOL_DURABLE_OBSERVER_INPUTS
from scripts.agent_dependencies_oracle import OBSERVER_INPUTS as AGENT_DEPENDENCIES_OBSERVER_INPUTS
from scripts.sdk_profile_oracle import OBSERVER_INPUTS as SDK_OBSERVER_INPUTS
from scripts.permission_presets_oracle import OBSERVER_INPUTS as PERMISSION_OBSERVER_INPUTS
from scripts.exported_host_lifecycle_oracle import observe_native as observe_host_lifecycle
from scripts.process_artifact_retention import prune_finished_test_folder
from scripts.llm_metadata_oracle import observation_digest as llm_metadata_observation_digest
from test_llm_metadata_consumers import damage_observations as damage_llm_metadata_observations
from scripts.canonical_llm_oracle import observation_digest as canonical_llm_observation_digest
from test_canonical_llm_consumers import damage_observations as damage_canonical_llm_observations
from scripts.jsonl_sharing_oracle import observation_digest as sharing_observation_digest
from test_jsonl_sharing_consumers import damage_observations as damage_sharing_observations


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('current_release_gate', ROOT / 'scripts/verify_release.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


@pytest.fixture(autouse=True)
def prune_completed_gate_test(request):
    yield
    folder = request.node.funcargs.get('tmp_path')
    factory = getattr(request.config, '_tmp_path_factory', None)
    workspace = getattr(factory, '_basetemp', None)
    if folder is not None and workspace is not None:
        prune_finished_test_folder(ROOT / '.goose/out', workspace, folder)


@pytest.mark.parametrize('damage', ['none', 'omit', 'skip', 'duplicate', 'failure'])
def test_actual_pytest_unicode_lane_identity_remains_mandatory(tmp_path, monkeypatch, damage):
    child = tmp_path / 'unicode-child'
    child.mkdir()
    test = child / 'test_win32_stat_consumers.py'
    test.write_text("import pytest\n@pytest.mark.parametrize('name', ['中文.txt'])\n"
                    "def test_actual_original_and_native_windows_stat_match(name):\n"
                    "    assert name == '中文.txt'\n", encoding='utf-8')
    output = child / 'pytest.xml'
    completed = subprocess.run([sys.executable, '-m', 'pytest', str(test), '-q',
        '--confcutdir=' + str(child), '--junitxml=' + str(output)], cwd=str(child), capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = ET.parse(str(output))
    suite = report.getroot().find('testsuite')
    case = suite.find('testcase')
    expected = 'test_actual_original_and_native_windows_stat_match[\\u4e2d\\u6587.txt]'
    assert case.get('name') == expected
    assert expected in GATE.REQUIRED_REGRESSION['test_win32_stat_consumers']
    monkeypatch.setattr(GATE, 'REQUIRED_REGRESSION', {'test_win32_stat_consumers': {expected}})
    if damage == 'omit':
        suite.remove(case)
    elif damage == 'skip':
        ET.SubElement(case, 'skipped')
    elif damage == 'duplicate':
        suite.append(copy.deepcopy(case))
    elif damage == 'failure':
        ET.SubElement(case, 'failure')
    report.write(str(output), encoding='utf-8')
    if damage == 'none':
        assert GATE.validate_regression(output) == {'required_lanes': 1, 'skipped': 0}
    else:
        with pytest.raises(RuntimeError):
            GATE.validate_regression(output)


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
    assert GATE.validate_regression(path) == {'required_lanes': sum(len(names) for names in GATE.REQUIRED_REGRESSION.values()), 'skipped': 1}


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


@functools.lru_cache(maxsize=1)
def redirect_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='redirect-validator-fixture-') as directory:
        output = Path(directory) / 'native.json'
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/oracles/http_redirect_python.py'),
                                 '--root', str(ROOT), '--output', str(output)], capture_output=True, timeout=45)
        assert result.returncode == 0 and not result.stderr, result.stderr
        return json.loads(output.read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'modules-missing',
                                   'module-changed', 'foreign-root', 'missing-observation'])
def test_extracted_redirect_requires_fresh_source_and_owned_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['httpRedirect']
    elif damage == 'source-missing':
        del candidate['http_redirect_observations_sha256']
    elif damage == 'source-changed':
        candidate['http_redirect_observations_sha256'] = '0' * 64
    elif damage == 'modules-missing':
        del candidate['http_redirect_modules']
    elif damage == 'module-changed':
        report['httpRedirect']['modules']['dsh/llm/http_stream.py'] = '0' * 64
    elif damage == 'foreign-root':
        report['httpRedirect']['root'] = str(tmp_path.parent)
    else:
        report['httpRedirect']['rows'].pop()
    path = tmp_path / 'extracted.json'
    path.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='httpRedirect'):
        GATE.validate_extracted(path, archive, candidate)


@functools.lru_cache(maxsize=1)
def javascript_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='javascript-workflow-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/javascript_workflow_oracle.py'),
                                 '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace'))
        paired = json.loads(output.read_text(encoding='utf-8'))
        assert paired['status'] == 'matched'
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'assets-missing', 'asset-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'changed', 'late-log'])
def test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['javascriptWorkflow']
    if damage == 'missing':
        del report['javascriptWorkflow']
    elif damage == 'source-missing':
        del candidate['javascript_workflow_observations_sha256']
    elif damage == 'source-changed':
        candidate['javascript_workflow_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/workflow/javascript_run.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/workflow/javascript_run.py'] = '0' * 64
    elif damage == 'assets-missing':
        del runtime['assets']['dsh/javascript/bin/dsh_js_worker.exe']
    elif damage == 'asset-changed':
        runtime['assets']['dsh/javascript/workflow/source.js'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path.parent / 'python.exe')
    elif damage == 'tail':
        runtime['observations'].pop()
    elif damage == 'duplicate':
        runtime['observations'][-1] = copy.deepcopy(runtime['observations'][0])
    elif damage == 'changed':
        runtime['observations'][0]['result']['value'][0] = 'forged'
    else:
        late = next(row for row in runtime['observations'] if row['name'] == 'dropped-child-continuation')
        late['events'].pop()
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='javascriptWorkflow'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('module', ['test_javascript_runtime', 'test_javascript_workflow_session',
    'test_javascript_workflow_host', 'test_javascript_workflow_consumers'])
@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_javascript_runtime_and_source_consumer_lanes_are_mandatory(tmp_path, module, damage):
    path = tmp_path / 'pytest.xml'
    key = (module, sorted(GATE.REQUIRED_REGRESSION[module])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def context_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='runtime-context-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/runtime_context_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'attribution', 'identity-correlation'])
def test_extracted_context_requires_source_identity_and_complete_messages(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['runtimeContext']
    if damage == 'missing':
        del report['runtimeContext']
    elif damage == 'source-missing':
        del candidate['runtime_context_observations_sha256']
    elif damage == 'source-changed':
        candidate['runtime_context_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/core/agent_loop.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/core/agent_loop.py'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path.parent / 'python.exe')
    elif damage == 'tail':
        runtime['observations'].pop()
    elif damage == 'duplicate':
        runtime['observations'][-1] = copy.deepcopy(runtime['observations'][0])
    elif damage == 'attribution':
        runtime['observations'][0]['snapshots'][0]['source']['sections'] = []
    else:
        runtime['observations'][0]['snapshots'][0]['id'] = 'foreign-message-identity'
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='runtimeContext'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_runtime_context_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_runtime_context_consumers', sorted(GATE.REQUIRED_REGRESSION['test_runtime_context_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def ready_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='javascript-ready-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/javascript_ready_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'assets-missing', 'asset-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'outcome', 'late-phase'])
def test_extracted_ready_requires_source_assets_and_complete_observations(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['javascriptReady']
    if damage == 'missing':
        del report['javascriptReady']
    elif damage == 'source-missing':
        del candidate['javascript_ready_observations_sha256']
    elif damage == 'source-changed':
        candidate['javascript_ready_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/javascript/runtime.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/javascript/runtime.py'] = '0' * 64
    elif damage == 'assets-missing':
        del runtime['assets']['dsh/javascript/bin/dsh_js_worker.exe']
    elif damage == 'asset-changed':
        runtime['assets']['dsh/javascript/workflow/source.js'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path.parent / 'python.exe')
    elif damage == 'tail':
        runtime['observations'].pop()
    elif damage == 'duplicate':
        runtime['observations'][-1] = copy.deepcopy(runtime['observations'][0])
    elif damage == 'outcome':
        runtime['observations'][0]['result']['error'] = 'workflow worker failed: JavaScript worker already exited'
    else:
        runtime['observations'][0]['events'].append(dict(type='phase', title='unreachable'))
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='javascriptReady'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_ready_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_javascript_ready_consumers', sorted(GATE.REQUIRED_REGRESSION['test_javascript_ready_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def read_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='persistence-read-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/persistence_read_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'assets-missing', 'asset-changed', 'root', 'python', 'executable', 'tail', 'duplicate',
    'outcome', 'late-return', 'signal', 'queue', 'legacy'])
def test_extracted_read_requires_source_assets_and_complete_observations(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['persistenceRead']
    if damage == 'missing':
        del report['persistenceRead']
    elif damage == 'source-missing':
        del candidate['persistence_read_observations_sha256']
    elif damage == 'source-changed':
        candidate['persistence_read_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/session/coordinator.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/session/coordinator.py'] = '0' * 64
    elif damage == 'assets-missing':
        del runtime['assets']['dsh/session/bin/zstd/dsh_zstd.dll']
    elif damage == 'asset-changed':
        runtime['assets']['dsh/session/bin/zstd/dsh_zstd.dll'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'tail':
        runtime['rows'].pop()
    elif damage == 'duplicate':
        runtime['rows'][-1] = copy.deepcopy(runtime['rows'][0])
    elif damage == 'outcome':
        runtime['rows'][0]['accepted'] = False
    elif damage == 'late-return':
        del next(row for row in runtime['rows'] if row['name'] == 'jsonl-none/abort/after-read')['error']
    elif damage == 'signal':
        next(row for row in runtime['rows'] if row['name'] == 'jsonl-none/abort/after-read')['calls'][0]['signalForwarded'] = False
    elif damage == 'queue':
        next(row for row in runtime['rows'] if row['name'] == 'sqlite/queued')['settledBeforeRelease'] = False
    else:
        next(row for row in runtime['rows'] if row['name'] == 'sqlite/legacy-forward')['calls'][0]['signalForwarded'] = False
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='persistenceRead'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_read_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_persistence_read_consumers', sorted(GATE.REQUIRED_REGRESSION['test_persistence_read_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def initial_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='javascript-initial-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/javascript_initial_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=60)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'assets-missing', 'asset-changed', 'root', 'python', 'executable', 'tail',
    'duplicate', 'outcome', 'late-phase', 'entry', 'emission'])
def test_extracted_initial_requires_source_assets_and_complete_observations(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['javascriptInitial']
    if damage == 'missing':
        del report['javascriptInitial']
    elif damage == 'source-missing':
        del candidate['javascript_initial_observations_sha256']
    elif damage == 'source-changed':
        candidate['javascript_initial_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/javascript/runtime.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/javascript/runtime.py'] = '0' * 64
    elif damage == 'assets-missing':
        del runtime['assets']['dsh/javascript/bin/dsh_js_worker.exe']
    elif damage == 'asset-changed':
        runtime['assets']['dsh/javascript/workflow/source.js'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'tail':
        runtime['observations'].pop()
    elif damage == 'duplicate':
        runtime['observations'][-1] = copy.deepcopy(runtime['observations'][0])
    elif damage == 'outcome':
        runtime['observations'][0]['result']['error'] = 'workflow worker failed: Connection lost'
    elif damage == 'late-phase':
        runtime['observations'][0]['events'].append(dict(type='phase', title='unreachable'))
    elif damage == 'entry':
        runtime['observations'][0]['before']['entryBlocked'] = False
    else:
        runtime['observations'][0]['before']['readyMessages'] = 1
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='javascriptInitial'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_initial_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_javascript_initial_consumers', sorted(GATE.REQUIRED_REGRESSION['test_javascript_initial_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def number_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='session-number-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/session_number_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'outcome', 'metadata', 'mutation', 'input',
    'clone-missing', 'clone-deep', 'clone-shallow', 'clone-original'])
def test_extracted_number_requires_source_and_complete_metadata(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['sessionNumber']
    if damage == 'missing':
        del report['sessionNumber']
    elif damage == 'source-missing':
        del candidate['session_number_observations_sha256']
    elif damage == 'source-changed':
        candidate['session_number_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/core/session/types.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/core/session/types.py'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'tail':
        runtime['rows'].pop()
    elif damage == 'duplicate':
        runtime['rows'][-1] = copy.deepcopy(runtime['rows'][0])
    elif damage == 'outcome':
        runtime['rows'][0]['accepted'] = False
    elif damage.startswith('clone-'):
        row = next(row for row in runtime['rows'] if row['name'] == ('shallow-copy' if damage == 'clone-shallow' else 'deep-copy'))
        if damage == 'clone-missing':
            del row['clone']
        elif damage in ('clone-deep', 'clone-shallow'):
            row['nestedMutationAccepted'] = damage == 'clone-shallow'
        else:
            row['header']['extra']['nested'].append(3)
    else:
        name = 'header-mutation' if damage == 'mutation' else 'unknown-field'
        row = next(row for row in runtime['rows'] if row['name'] == name)
        if damage == 'metadata':
            del row['header']['extra']
        elif damage == 'mutation':
            row['mutationAccepted'] = True
        else:
            row['input']['extra']['nested'].append(3)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sessionNumber'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_number_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_session_number_consumers', sorted(GATE.REQUIRED_REGRESSION['test_session_number_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def diagnostic_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='session-diagnostic-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/session_diagnostic_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'accepted',
    'error-name', 'error-text', 'lossless-first', 'restore-negative-zero'])
def test_extracted_diagnostic_requires_exact_errors_and_source(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['sessionDiagnostic']
    if damage == 'missing':
        del report['sessionDiagnostic']
    elif damage == 'source-missing':
        del candidate['session_diagnostic_observations_sha256']
    elif damage == 'source-changed':
        candidate['session_diagnostic_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/cordis/utils.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/cordis/utils.py'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'tail':
        runtime['rows'].pop()
    elif damage == 'duplicate':
        runtime['rows'][-1] = copy.deepcopy(runtime['rows'][0])
    elif damage == 'accepted':
        runtime['rows'][0]['accepted'] = not runtime['rows'][0]['accepted']
    elif damage == 'error-name':
        runtime['rows'][0]['error']['name'] = 'ValueError'
    elif damage == 'error-text':
        next(row for row in runtime['rows'] if row['name'] == 'create/version/empty-array')['error']['message'] = 'got []'
    elif damage == 'lossless-first':
        next(row for row in runtime['rows'] if row['name'] == 'create/version/nan')['error']['message'] = 'got NaN'
    else:
        next(row for row in runtime['rows'] if row['name'] == 'restore/version/negative-zero')['accepted'] = False
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sessionDiagnostic'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_diagnostic_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_session_diagnostic_consumers', sorted(GATE.REQUIRED_REGRESSION['test_session_diagnostic_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def restore_sign_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='session-restore-sign-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/session_restore_sign_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'accepted',
    'signed-zero', 'input-value', 'safe-integer', 'error-text'])
def test_extracted_restore_sign_requires_numeric_identity_and_source(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['sessionRestoreSign']
    if damage == 'missing':
        del report['sessionRestoreSign']
    elif damage == 'source-missing':
        del candidate['session_restore_sign_observations_sha256']
    elif damage == 'source-changed':
        candidate['session_restore_sign_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/core/session/types.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/core/session/types.py'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'tail':
        runtime['rows'].pop()
    elif damage == 'duplicate':
        runtime['rows'][-1] = copy.deepcopy(runtime['rows'][0])
    elif damage == 'accepted':
        runtime['rows'][0]['accepted'] = False
    elif damage in ('signed-zero', 'input-value', 'safe-integer'):
        row = next(row for row in runtime['rows'] if row['name'] == 'createdAt/negative-zero')
        row[{'signed-zero': 'negativeZero', 'input-value': 'equalInput', 'safe-integer': 'safeInteger'}[damage]] = False
    else:
        next(row for row in runtime['rows'] if row['name'] == 'version/fraction')['error']['message'] = 'wrong version'
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sessionRestoreSign'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_restore_sign_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_session_restore_sign_consumers', sorted(GATE.REQUIRED_REGRESSION['test_session_restore_sign_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def full_request_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='runtime-full-request-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/runtime_full_request_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'provider',
    'assistant-alias', 'token-alias', 'reasoning-alias', 'message-owner', 'signal-owner', 'signal-state'])
def test_extracted_full_request_requires_complete_graph_and_source(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['runtimeFullRequest']
    if damage == 'missing':
        del report['runtimeFullRequest']
    elif damage == 'source-missing':
        del candidate['runtime_full_request_observations_sha256']
    elif damage == 'source-changed':
        candidate['runtime_full_request_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/llm/llm_service.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/llm/llm_service.py'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'tail':
        runtime['observations'].pop()
    elif damage == 'duplicate':
        runtime['observations'][-1] = copy.deepcopy(runtime['observations'][0])
    else:
        row = runtime['observations'][0]
        if damage == 'provider':
            row['requests'][0]['provider'] = 'foreign'
        elif damage == 'assistant-alias':
            next(message for message in row['requests'][1]['messages'] if message['role'] == 'assistant')['tool_calls'] = []
        elif damage == 'token-alias':
            next(row for row in runtime['observations'] if row['name'] == 'change/max-tokens')['requests'][0]['max_tokens'] = 17
        elif damage == 'reasoning-alias':
            next(row for row in runtime['observations'] if row['name'] == 'change/reasoning')['requests'][0]['reasoning_effort'] = 'high'
        elif damage == 'message-owner':
            row['requests'][1]['messages'][0]['id'] = 'foreign-detached-id'
        elif damage == 'signal-owner':
            row['requests'][1]['signal']['sameAsFirst'] = False
        else:
            row['requests'][0]['signal']['aborted'] = True
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='runtimeFullRequest'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_full_request_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_runtime_full_request_consumers', sorted(GATE.REQUIRED_REGRESSION['test_runtime_full_request_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def deepseek_error_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='deepseek-error-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/deepseek_error_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ['missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed',
    'root', 'python', 'executable', 'tail', 'duplicate', 'error-name', 'error-message',
    'failure-message', 'preview', 'surrogate', 'timer', 'fraction', 'chunk', 'request-body'])
def test_extracted_deepseek_error_requires_complete_rows_and_source(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['deepseekError']
    if damage == 'missing':
        del report['deepseekError']
    elif damage == 'source-missing':
        del candidate['deepseek_error_observations_sha256']
    elif damage == 'source-changed':
        candidate['deepseek_error_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/llm/deepseek_wire.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/llm/deepseek_wire.py'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    else:
        damage_observations(runtime, damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='deepseekError'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_deepseek_error_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_deepseek_error_consumers', sorted(GATE.REQUIRED_REGRESSION['test_deepseek_error_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def deepseek_capture_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='deepseek-capture-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/deepseek_capture_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=90)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ('missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'config-name', 'config-message', 'error-name', 'error-message', 'failure-message', 'error-code', 'file-message', 'file-failure', 'file-quota', 'file-status', 'settings-model', 'settings-provider', 'settings-retry', 'stream', 'serialization', 'usage', 'request-body', 'accepted', 'origin', 'retry-failure', 'retry-delay', 'retry-policy', 'retry-number', 'retry-split', 'retry-shared', 'retry-form', 'tail', 'duplicate', 'root', 'python', 'executable'))

def test_extracted_deepseek_capture_requires_complete_rows_and_source(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['deepseekCapture']
    if damage == 'missing':
        del report['deepseekCapture']
    elif damage == 'source-missing':
        del candidate['deepseek_capture_observations_sha256']
    elif damage == 'source-changed':
        candidate['deepseek_capture_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/llm/deepseek_config.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/llm/deepseek_config.py'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    else:
        damage_capture_observations(runtime, damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='deepseekCapture'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ['omit', 'skip', 'duplicate', 'failure'])
def test_deepseek_capture_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_deepseek_capture_consumers', sorted(GATE.REQUIRED_REGRESSION['test_deepseek_capture_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def sharing_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='jsonl-sharing-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/jsonl_sharing_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=180)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ('missing', 'source-missing', 'source-changed', 'module-missing',
    'module-changed', 'root', 'python', 'executable', 'header', 'event', 'raw', 'filename', 'tail', 'duplicate', 'order'))
def test_extracted_jsonl_sharing_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['jsonlSharing']
    if damage == 'missing':
        del report['jsonlSharing']
    elif damage == 'source-missing':
        del candidate['jsonl_sharing_observations_sha256']
    elif damage == 'source-changed':
        candidate['jsonl_sharing_observations_sha256'] = '0' * 64
    elif damage == 'module-missing':
        del runtime['modules']['dsh/session/file_io.py']
    elif damage == 'module-changed':
        runtime['modules']['dsh/session/file_io.py'] = '0' * 64
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    else:
        damage_sharing_observations(runtime, damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='jsonlSharing'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_jsonl_sharing_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_jsonl_sharing_consumers', sorted(GATE.REQUIRED_REGRESSION['test_jsonl_sharing_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def canonical_llm_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='canonical-llm-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/canonical_llm_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=600)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ('missing', 'source-missing', 'source-changed', 'module-changed', 'request', 'event', 'tool-id', 'message-form', 'message-split', 'message-cross-fixture', 'retry-form', 'retry-split', 'retry-cross-fixture', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module'))
def test_extracted_canonical_llm_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['canonicalLlm']
    if damage == 'missing':
        del report['canonicalLlm']
    elif damage == 'source-missing':
        del candidate['canonical_llm_observations_sha256']
    elif damage == 'source-changed':
        candidate['canonical_llm_observations_sha256'] = '0' * 64
    elif damage == 'module-changed':
        runtime['modules']['dsh/llm/adapter_failure.py'] = '0' * 64
    elif damage == 'module':
        del runtime['modules']['dsh/llm/adapter_failure.py']
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'group-missing':
        del runtime['groups']['iterator']
    elif damage == 'group-rows':
        runtime['groups']['iterator']['rows'].pop()
    elif damage == 'group-root':
        runtime['groups']['iterator']['root'] = str(tmp_path.parent)
    elif damage == 'group-executable':
        runtime['groups']['iterator']['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'group-module':
        del runtime['groups']['iterator']['modules']['dsh/llm/llm_service.py']
    else:
        damage_canonical_llm_observations(runtime, damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='canonicalLlm'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_canonical_llm_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_canonical_llm_consumers', sorted(GATE.REQUIRED_REGRESSION['test_canonical_llm_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def llm_metadata_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='llm-metadata-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/llm_metadata_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=600)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ('missing', 'source-missing', 'source-changed', 'module-changed', 'model', 'context', 'reasoning', 'description', 'max-tokens', 'modalities', 'trace', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module'))
def test_extracted_llm_metadata_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['llmMetadata']
    if damage == 'missing':
        del report['llmMetadata']
    elif damage == 'source-missing':
        del candidate['llm_metadata_observations_sha256']
    elif damage == 'source-changed':
        candidate['llm_metadata_observations_sha256'] = '0' * 64
    elif damage == 'module-changed':
        runtime['modules']['dsh/llm/model_info.py'] = '0' * 64
    elif damage == 'module':
        del runtime['modules']['dsh/llm/model_info.py']
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'group-missing':
        del runtime['groups']['stream']
    elif damage == 'group-rows':
        runtime['groups']['stream']['rows'].pop()
    elif damage == 'group-root':
        runtime['groups']['stream']['root'] = str(tmp_path.parent)
    elif damage == 'group-executable':
        runtime['groups']['stream']['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'group-module':
        del runtime['groups']['stream']['modules']['dsh/llm/llm_service.py']
    else:
        damage_llm_metadata_observations(runtime, damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='llmMetadata'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_llm_metadata_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_llm_metadata_consumers', sorted(GATE.REQUIRED_REGRESSION['test_llm_metadata_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def llm_prepared_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='llm-prepared-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/llm_prepared_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=600)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ('missing', 'source-missing', 'source-changed', 'module-changed', 'config', 'boolean', 'defaults', 'context', 'error', 'dispatch', 'trace', 'replay', 'signal', 'frozen', 'header', 'empty', 'message-form', 'message-split', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module'))
def test_extracted_llm_prepared_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['llmPrepared']
    if damage == 'missing':
        del report['llmPrepared']
    elif damage == 'source-missing':
        del candidate['llm_prepared_observations_sha256']
    elif damage == 'source-changed':
        candidate['llm_prepared_observations_sha256'] = '0' * 64
    elif damage == 'module-changed':
        runtime['modules']['dsh/llm/call_config.py'] = '0' * 64
    elif damage == 'module':
        del runtime['modules']['dsh/llm/call_config.py']
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'group-missing':
        del runtime['groups']['agent']
    elif damage == 'group-rows':
        runtime['groups']['agent']['rows'].pop()
    elif damage == 'group-root':
        runtime['groups']['agent']['root'] = str(tmp_path.parent)
    elif damage == 'group-executable':
        runtime['groups']['agent']['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'group-module':
        del runtime['groups']['agent']['modules']['dsh/llm/llm_service.py']
    else:
        damage_llm_prepared_observations(runtime, damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='llmPrepared'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_llm_prepared_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_llm_prepared_consumers', sorted(GATE.REQUIRED_REGRESSION['test_llm_prepared_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def llm_config_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='llm-config-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/llm_config_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=600)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('damage', ('missing', 'source-missing', 'source-changed', 'module-changed', 'config', 'boolean', 'max-null', 'reason-null', 'same', 'same-stop', 'input', 'after-change', 'error', 'code', 'hook', 'signal', 'trace', 'tail', 'duplicate', 'order', 'type', 'unknown', 'root', 'python', 'executable', 'module', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module'))
def test_extracted_llm_config_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['llmConfig']
    if damage == 'missing':
        del report['llmConfig']
    elif damage == 'source-missing':
        del candidate['llm_config_observations_sha256']
    elif damage == 'source-changed':
        candidate['llm_config_observations_sha256'] = '0' * 64
    elif damage == 'module-changed':
        runtime['modules']['dsh/llm/call_config.py'] = '0' * 64
    elif damage == 'module':
        del runtime['modules']['dsh/llm/call_config.py']
    elif damage == 'root':
        runtime['root'] = str(tmp_path.parent)
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign runtime'
    elif damage == 'executable':
        runtime['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'group-missing':
        del runtime['groups']['query']
    elif damage == 'group-rows':
        runtime['groups']['query']['rows'].pop()
    elif damage == 'group-root':
        runtime['groups']['query']['root'] = str(tmp_path.parent)
    elif damage == 'group-executable':
        runtime['groups']['query']['executable'] = str(tmp_path / 'nested/python.exe')
    elif damage == 'group-module':
        del runtime['groups']['query']['modules']['dsh/llm/llm_service.py']
    else:
        damage_llm_config_observations(runtime, damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='llmConfig'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_llm_config_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_llm_config_consumers', sorted(GATE.REQUIRED_REGRESSION['test_llm_config_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def win32_stat_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='win32-stat-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/win32_stat_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=300)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return dict(source=json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
            native=json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('damage', ('missing', 'source-missing', 'source-hash', 'source-row', 'source-stamp',
    'module-changed', 'stat-version', 'lstat-version', 'directory-size', 'change-time', 'file-identity',
    'missing-file', 'order', 'row', 'unknown', 'size-type', 'module', 'root', 'python', 'executable', 'workspace',
    'probe-count', 'handle-leak', 'failure-missing', 'failure-code', 'failure-close', 'failure-order', 'failure-type'))
def test_extracted_windows_stat_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['win32Stat']
    if damage == 'missing':
        del report['win32Stat']
    elif damage == 'source-missing':
        del candidate['win32_stat_source']
    elif damage == 'source-hash':
        candidate['win32_stat_source_sha256'] = '0' * 64
    elif damage == 'source-row':
        candidate['win32_stat_source']['rows'][0]['stat']['version'] += 'foreign'
    elif damage == 'source-stamp':
        del report['win32StatSourceSha256']
    elif damage == 'module-changed':
        runtime['modules']['dsh/fs/win32_stat.py'] = '0' * 64
    else:
        damage_win32_stat_runtime(runtime, 'missing' if damage == 'missing-file' else damage, tmp_path)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='win32Stat'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_windows_stat_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_win32_stat_consumers', sorted(GATE.REQUIRED_REGRESSION['test_win32_stat_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def sdk_profile_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='dsh-sdk-profile-source-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/sdk_profile_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=600)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return dict(source=json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
            native=json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@functools.lru_cache(maxsize=1)
def permission_presets_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='dsh-permission-presets-source-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/permission_presets_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=240)
        if completed.returncode:
            raise RuntimeError((completed.stdout + completed.stderr).decode('utf-8', errors='replace'))
        return dict(source=json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
            native=json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@functools.lru_cache(maxsize=1)
def tool_errors_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='dsh-tool-errors-source-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/tool_errors_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=240)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return dict(source=json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
            native=json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@functools.lru_cache(maxsize=1)
def host_lifecycle_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='dsh-host-lifecycle-') as folder:
        return observe_host_lifecycle(ROOT, sys.executable, Path(folder) / 'native.json')


@pytest.mark.parametrize('damage', GATE.TOOL_ERROR_DAMAGES + ('missing', 'source-missing', 'source-changed', 'source-file'))
def test_extracted_tool_errors_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['toolErrors']
    elif damage == 'source-missing':
        del candidate['tool_errors_source']
    elif damage == 'source-changed':
        candidate['tool_errors_source']['rows'][0]['present'] = True
    elif damage == 'source-file':
        report['toolErrorsSourceSha256'] = '0' * 64
    else:
        report['toolErrors'] = damage_tool_error_runtime(report['toolErrors'], damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='toolErrors'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_tool_errors_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    for module in ('test_tool_errors_consumers', 'test_exported_host_metadata'):
        for name in GATE.REQUIRED_REGRESSION[module]:
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ('missing', 'row', 'tail', 'order', 'module', 'fixture', 'root', 'python', 'executable', 'counter'))
def test_extracted_host_lifecycle_requires_owned_complete_observations(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    runtime = report['exportedHostLifecycle']
    if damage == 'missing':
        del report['exportedHostLifecycle']
    elif damage == 'row':
        runtime['rows'][1]['republished'] = True
    elif damage == 'tail':
        runtime['rows'].pop()
    elif damage == 'order':
        runtime['rows'].reverse()
    elif damage == 'module':
        runtime['imports']['dsh/extensions/packaged_host.py'] = '0' * 64
    elif damage == 'fixture':
        runtime['fixtureSha256'] = '0' * 64
    elif damage == 'root':
        runtime['root'] += '-foreign'
    elif damage == 'python':
        runtime['python'] = '3.9.0 foreign'
    elif damage == 'executable':
        runtime['executable'] += '-foreign'
    else:
        runtime['rows'][0]['restoredCounter'] = 1
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='exportedHostLifecycle'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', GATE.PERMISSION_EXTRACTED_DAMAGES)
def test_extracted_permission_presets_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['permissionPresets']
    elif damage == 'source-missing':
        del candidate['permission_presets_source']
    elif damage == 'source-hash':
        candidate['permission_presets_source_sha256'] = '0' * 64
    elif damage == 'source-stamp':
        del report['permissionPresetsSourceSha256']
    elif damage.startswith('source-'):
        candidate['permission_presets_source'] = damage_permission_source(candidate['permission_presets_source'], damage[len('source-'):])
    else:
        report['permissionPresets'] = damage_permission_runtime(report['permissionPresets'], damage, tmp_path / 'foreign-runtime')
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='permissionPresets'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_permission_presets_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    for name in GATE.REQUIRED_REGRESSION['test_permission_presets_consumers']:
        regression_xml(path, **{damage: ('test_permission_presets_consumers', name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('damage', SDK_EXTRACTED_DAMAGES)
def test_extracted_sdk_profile_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['sdkProfile']
    elif damage == 'source-missing':
        del candidate['sdk_profile_source']
    elif damage == 'source-hash':
        candidate['sdk_profile_source_sha256'] = '0' * 64
    elif damage == 'source-row':
        candidate['sdk_profile_source']['rows'].pop()
    elif damage == 'source-stamp':
        del report['sdkProfileSourceSha256']
    elif damage == 'source-input-shape':
        candidate['sdk_profile_source']['inputs']['reference/apps/cli/src/bin.ts'] = True
    else:
        damage_sdk_profile_runtime(report['sdkProfile'], damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='sdkProfile'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_sdk_profile_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_sdk_profile_consumers', sorted(GATE.REQUIRED_REGRESSION['test_sdk_profile_consumers'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_workflow_session_boundary_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    for name in GATE.REQUIRED_REGRESSION['test_workflow_session_boundary']:
        regression_xml(path, **{damage: ('test_workflow_session_boundary', name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_preflight_copy_retention_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    for name in GATE.REQUIRED_REGRESSION['test_preflight_copy_retention']:
        regression_xml(path, **{damage: ('test_preflight_copy_retention', name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_windows_confined_console_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    for name in GATE.REQUIRED_REGRESSION['test_windows_confined_console']:
        regression_xml(path, **{damage: ('test_windows_confined_console', name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def javascript_errors_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='javascript-errors-receipt-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/javascript_errors_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=360)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return dict(source=json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
            native=json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('damage', GATE.JS_ERROR_DAMAGES + ('missing', 'source-missing', 'source-changed', 'source-file'))
def test_extracted_javascript_errors_requires_complete_values_and_assets(tmp_path, damage):
    from scripts.javascript_errors_cases import damage_runtime
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'missing':
        del report['javascriptErrors']
    elif damage == 'source-missing':
        del candidate['javascript_errors_source']
    elif damage == 'source-changed':
        candidate['javascript_errors_source']['rows'][0]['body'] = 'return 42'
    elif damage == 'source-file':
        report['javascriptErrorsSourceSha256'] = '0' * 64
    else:
        report['javascriptErrors'] = damage_runtime(report['javascriptErrors'], damage, tmp_path / 'foreign')
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='javascriptErrors'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_javascript_errors_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    for name in GATE.REQUIRED_REGRESSION['test_javascript_errors_consumers']:
        regression_xml(path, **{damage: ('test_javascript_errors_consumers', name)})
        with pytest.raises(RuntimeError):
            GATE.validate_regression(path)


def extracted_receipt(tmp_path):
    archive = tmp_path / 'portable.zip'
    archive.write_bytes(b'exact candidate archive')
    candidate = {'product_commit': 'a' * 40, 'worktree_dirty': False}
    scheduler = copy.deepcopy(scheduler_runtime_fixture())
    scheduler['root'] = str(tmp_path)
    candidate['tool_scheduler_observations_sha256'] = scheduler_observation_digest(scheduler['rows'])
    candidate['tool_scheduler_modules'] = scheduler['modules'].copy()
    redirect = copy.deepcopy(redirect_runtime_fixture())
    redirect['root'] = str(tmp_path)
    candidate['http_redirect_observations_sha256'] = redirect_observation_digest(redirect['rows'])
    candidate['http_redirect_modules'] = redirect['modules'].copy()
    javascript = copy.deepcopy(javascript_runtime_fixture())
    javascript['root'], javascript['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['javascript_workflow_observations_sha256'] = javascript_observation_digest(javascript['observations'])
    candidate['javascript_workflow_modules'] = javascript['modules'].copy()
    candidate['javascript_workflow_assets'] = javascript['assets'].copy()
    context = copy.deepcopy(context_runtime_fixture())
    context['root'], context['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['runtime_context_observations_sha256'] = context_observation_digest(context['observations'])
    candidate['runtime_context_modules'] = context['modules'].copy()
    ready = copy.deepcopy(ready_runtime_fixture())
    ready['root'], ready['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['javascript_ready_observations_sha256'] = ready_observation_digest(ready['observations'])
    candidate['javascript_ready_modules'] = ready['modules'].copy()
    candidate['javascript_ready_assets'] = ready['assets'].copy()
    initial = copy.deepcopy(initial_runtime_fixture())
    initial['root'], initial['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['javascript_initial_observations_sha256'] = initial_observation_digest(initial['observations'])
    candidate['javascript_initial_modules'] = initial['modules'].copy()
    candidate['javascript_initial_assets'] = initial['assets'].copy()
    errors_pair = copy.deepcopy(javascript_errors_runtime_fixture())
    errors = errors_pair['native']
    errors['root'], errors['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    for child in errors['groups'].values():
        child['root'], child['executable'] = errors['root'], errors['executable']
    candidate['javascript_errors_source'] = errors_pair['source']
    candidate['javascript_errors_source_sha256'] = hashlib.sha256(json.dumps(errors_pair['source'], sort_keys=True).encode('utf-8')).hexdigest()
    candidate['javascript_errors_observations_sha256'] = GATE.errors_identity(errors_pair['source'])
    candidate['javascript_errors_modules'] = copy.deepcopy(errors['modules'])
    candidate['javascript_errors_assets'] = copy.deepcopy(errors['assets'])
    read = copy.deepcopy(read_runtime_fixture())
    read['root'], read['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['persistence_read_observations_sha256'] = read_observation_digest(read['rows'])
    candidate['persistence_read_modules'] = read['modules'].copy()
    candidate['persistence_read_assets'] = read['assets'].copy()
    number = copy.deepcopy(number_runtime_fixture())
    number['root'], number['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['session_number_observations_sha256'] = number_observation_digest(number['rows'])
    candidate['session_number_modules'] = number['modules'].copy()
    diagnostic = copy.deepcopy(diagnostic_runtime_fixture())
    diagnostic['root'], diagnostic['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['session_diagnostic_observations_sha256'] = diagnostic_observation_digest(diagnostic['rows'])
    candidate['session_diagnostic_modules'] = diagnostic['modules'].copy()
    restore_sign = copy.deepcopy(restore_sign_runtime_fixture())
    restore_sign['root'], restore_sign['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['session_restore_sign_observations_sha256'] = restore_sign_observation_digest(restore_sign['rows'])
    candidate['session_restore_sign_modules'] = restore_sign['modules'].copy()
    full_request = copy.deepcopy(full_request_runtime_fixture())
    full_request['root'], full_request['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['runtime_full_request_observations_sha256'] = full_request_observation_digest(full_request['observations'])
    candidate['runtime_full_request_modules'] = full_request['modules'].copy()
    deepseek_error = copy.deepcopy(deepseek_error_runtime_fixture())
    deepseek_error['root'], deepseek_error['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['deepseek_error_observations_sha256'] = deepseek_error_observation_digest(deepseek_error['rows'])
    candidate['deepseek_error_modules'] = deepseek_error['modules'].copy()
    deepseek_capture = copy.deepcopy(deepseek_capture_runtime_fixture())
    deepseek_capture['root'], deepseek_capture['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['deepseek_capture_observations_sha256'] = deepseek_capture_observation_digest(deepseek_capture['rows'])
    candidate['deepseek_capture_modules'] = deepseek_capture['modules'].copy()
    sharing = copy.deepcopy(sharing_runtime_fixture())
    sharing['root'], sharing['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['jsonl_sharing_observations_sha256'] = sharing_observation_digest(sharing['rows'])
    candidate['jsonl_sharing_modules'] = sharing['modules'].copy()
    canonical_llm = copy.deepcopy(canonical_llm_runtime_fixture())
    canonical_llm['root'], canonical_llm['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    for child in canonical_llm['groups'].values():
        child['root'], child['executable'] = canonical_llm['root'], canonical_llm['executable']
    candidate['canonical_llm_observations_sha256'] = canonical_llm_observation_digest(canonical_llm['rows'])
    candidate['canonical_llm_modules'] = canonical_llm['modules'].copy()
    llm_metadata = copy.deepcopy(llm_metadata_runtime_fixture())
    llm_metadata['root'], llm_metadata['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    for child in llm_metadata['groups'].values():
        child['root'], child['executable'] = llm_metadata['root'], llm_metadata['executable']
    candidate['llm_metadata_observations_sha256'] = llm_metadata_observation_digest(llm_metadata['rows'])
    candidate['llm_metadata_modules'] = llm_metadata['modules'].copy()


    llm_prepared = copy.deepcopy(llm_prepared_runtime_fixture())
    llm_prepared['root'], llm_prepared['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    for child in llm_prepared['groups'].values():
        child['root'], child['executable'] = llm_prepared['root'], llm_prepared['executable']
    candidate['llm_prepared_observations_sha256'] = llm_prepared_observation_digest(llm_prepared['rows'])
    candidate['llm_prepared_modules'] = llm_prepared['modules'].copy()


    llm_config = copy.deepcopy(llm_config_runtime_fixture())
    llm_config['root'], llm_config['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    for child in llm_config['groups'].values():
        child['root'], child['executable'] = llm_config['root'], llm_config['executable']
    candidate['llm_config_observations_sha256'] = llm_config_observation_digest(llm_config['rows'])
    candidate['llm_config_modules'] = llm_config['modules'].copy()
    win32_stat_pair = copy.deepcopy(win32_stat_runtime_fixture())
    win32_stat = win32_stat_pair['native']
    win32_stat['root'], win32_stat['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['win32_stat_source'] = win32_stat_pair['source']
    candidate['win32_stat_source_sha256'] = hashlib.sha256(json.dumps(win32_stat_pair['source'], sort_keys=True).encode('utf-8')).hexdigest()
    candidate['win32_stat_modules'] = win32_stat['modules'].copy()
    sdk_profile_pair = copy.deepcopy(sdk_profile_runtime_fixture())
    sdk_profile = sdk_profile_pair['native']
    sdk_profile_pair['source']['inputs'] = {name: sha256 for name, sha256 in sdk_profile_pair['source']['inputs'].items()
        if name in SDK_OBSERVER_INPUTS or name in ('reference/apps/cli/src/bin.ts', 'reference/packages/sdk/server/src/index.ts')}
    sdk_profile['root'], sdk_profile['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    for capture in sdk_profile['captures'].values():
        capture['runtime']['root'], capture['runtime']['executable'] = sdk_profile['root'], sdk_profile['executable']
    candidate['sdk_profile_source'] = sdk_profile_pair['source']
    candidate['sdk_profile_source_sha256'] = hashlib.sha256(json.dumps(sdk_profile_pair['source'], sort_keys=True).encode('utf-8')).hexdigest()
    candidate['sdk_profile_modules'] = copy.deepcopy(sdk_profile['modules'])
    permission_pair = copy.deepcopy(permission_presets_runtime_fixture())
    permission_presets = permission_pair['native']
    permission_pair['source']['inputs'] = {name: sha256 for name, sha256 in permission_pair['source']['inputs'].items()
        if name in PERMISSION_OBSERVER_INPUTS or name == 'reference/packages/interaction/permission-presets/src/index.ts'}
    permission_presets['root'], permission_presets['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    for child in permission_presets['groups'].values():
        child['root'], child['executable'] = permission_presets['root'], permission_presets['executable']
    candidate['permission_presets_source'] = permission_pair['source']
    candidate['permission_presets_source_sha256'] = hashlib.sha256(json.dumps(permission_pair['source'], sort_keys=True).encode('utf-8')).hexdigest()
    candidate['permission_presets_source_identity_sha256'] = GATE.permission_presets_source_digest(permission_pair['source'])
    candidate['permission_presets_modules'] = copy.deepcopy(permission_presets['modules'])
    tool_pair = copy.deepcopy(tool_errors_runtime_fixture())
    tool_errors = tool_pair['native']
    tool_errors['root'], tool_errors['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    tool_pair['source']['inputs'] = {name: sha256 for name, sha256 in tool_pair['source']['inputs'].items()
        if name in TOOL_ERROR_OBSERVER_INPUTS or name == 'reference/packages/core/tools/src/index.ts'}
    candidate['tool_errors_source'] = tool_pair['source']
    candidate['tool_errors_source_sha256'] = hashlib.sha256(json.dumps(tool_pair['source'], sort_keys=True).encode('utf-8')).hexdigest()
    candidate['tool_errors_observations_sha256'] = GATE.tool_errors_digest(tool_pair['source']['rows'])
    candidate['tool_errors_modules'] = copy.deepcopy(tool_errors['imports'])
    tool_pair = copy.deepcopy(tool_durable_runtime_fixture())
    tool_durable = tool_pair['native']
    tool_durable['root'], tool_durable['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    tool_pair['source']['inputs'] = {name: sha256 for name, sha256 in tool_pair['source']['inputs'].items()
        if name in TOOL_DURABLE_OBSERVER_INPUTS or name in ('reference/packages/core/tools/src/index.ts', 'reference/packages/core/agent-loop/src/tool-calls.ts', 'reference/packages/llm/llm/src/message.ts')}
    candidate['tool_durable_source'] = tool_pair['source']
    candidate['tool_durable_source_sha256'] = hashlib.sha256(json.dumps(tool_pair['source'], sort_keys=True).encode('utf-8')).hexdigest()
    candidate['tool_durable_observations_sha256'] = GATE.tool_durable_digest(tool_pair['source']['rows'])
    candidate['tool_durable_modules'] = copy.deepcopy(tool_durable['imports'])
    tool_pair = copy.deepcopy(agent_dependencies_runtime_fixture())
    agent_dependencies = tool_pair['native']
    agent_dependencies['root'], agent_dependencies['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    tool_pair['source']['inputs'] = {name: sha256 for name, sha256 in tool_pair['source']['inputs'].items()
        if name in AGENT_DEPENDENCIES_OBSERVER_INPUTS or name in ('reference/packages/core/tools/src/index.ts', 'reference/packages/core/agent-loop/src/index.ts', 'reference/packages/core/agent/src/index.ts', 'reference/packages/core/session/src/index.ts', 'reference/packages/llm/llm/src/index.ts')}
    candidate['agent_dependencies_source'] = tool_pair['source']
    candidate['agent_dependencies_source_sha256'] = hashlib.sha256(json.dumps(tool_pair['source'], sort_keys=True).encode('utf-8')).hexdigest()
    candidate['agent_dependencies_observations_sha256'] = GATE.agent_dependencies_digest(tool_pair['source']['rows'])
    candidate['agent_dependencies_modules'] = copy.deepcopy(agent_dependencies['imports'])
    host_lifecycle = copy.deepcopy(host_lifecycle_runtime_fixture())
    host_lifecycle['root'], host_lifecycle['executable'] = str(tmp_path), str(tmp_path / 'python.exe')
    candidate['exported_host_lifecycle_sha256'] = GATE.host_lifecycle_digest(host_lifecycle)
    candidate['exported_host_lifecycle_modules'] = copy.deepcopy(host_lifecycle['imports'])
    candidate['exported_host_lifecycle_fixture_sha256'] = host_lifecycle['fixtureSha256']


    report = {'result': 'passed', 'browser': {'passed': True}, 'runtime': {'checks': ['actual runtime']},
              'acp': {'processes': 2, 'steps': ['initialize-0', 'invalid-params-before-effects',
                  'persistent-new', 'close-list-0', 'eof-0', 'initialize-1',
                  'new-process-resume-no-history-updates', 'close-list-1', 'eof-1']},
              'runtimeStderr': '', 'frontendFilesChecked': 119, 'archive': str(archive),
              'archiveSha256': GATE.digest(archive), 'provenance': dict(candidate), 'toolScheduler': scheduler,
              'httpRedirect': redirect, 'javascriptWorkflow': javascript, 'runtimeContext': context, 'javascriptReady': ready,
              'persistenceRead': read, 'javascriptInitial': initial, 'sessionNumber': number, 'sessionDiagnostic': diagnostic,
              'sessionRestoreSign': restore_sign, 'runtimeFullRequest': full_request, 'deepseekError': deepseek_error, 'deepseekCapture': deepseek_capture, 'jsonlSharing': sharing, 'canonicalLlm': canonical_llm, 'llmMetadata': llm_metadata, 'llmPrepared': llm_prepared, 'llmConfig': llm_config,
              'win32Stat': win32_stat, 'win32StatSourceSha256': candidate['win32_stat_source_sha256'],
              'sdkProfile': sdk_profile, 'sdkProfileSourceSha256': candidate['sdk_profile_source_sha256'],
              'permissionPresets': permission_presets, 'permissionPresetsSourceSha256': candidate['permission_presets_source_sha256'],
              'toolErrors': tool_errors, 'toolErrorsSourceSha256': candidate['tool_errors_source_sha256'],
              'toolDurable': tool_durable, 'toolDurableSourceSha256': candidate['tool_durable_source_sha256'],
              'agentDependencies': agent_dependencies, 'agentDependenciesSourceSha256': candidate['agent_dependencies_source_sha256'],
              'exportedHostLifecycle': host_lifecycle,
              'javascriptErrors': errors, 'javascriptErrorsSourceSha256': candidate['javascript_errors_source_sha256']}
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


@functools.lru_cache(maxsize=1)
def agent_dependencies_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='dsh-agent-dependencies-source-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/agent_dependencies_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=240)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return dict(source=json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
            native=json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))


@pytest.mark.parametrize('damage', GATE.AGENT_DEPENDENCIES_DAMAGES + ('receipt-missing', 'source-missing', 'source-changed', 'source-file'))
def test_extracted_agent_dependencies_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'receipt-missing':
        del report['agentDependencies']
    elif damage == 'source-missing':
        del candidate['agent_dependencies_source']
    elif damage == 'source-changed':
        candidate['agent_dependencies_source']['rows'][0]['active'] = True
    elif damage == 'source-file':
        report['agentDependenciesSourceSha256'] = '0' * 64
    else:
        report['agentDependencies'] = damage_agent_dependencies_runtime(report['agentDependencies'], damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='agentDependencies'):
        GATE.validate_extracted(output, archive, candidate)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_agent_dependencies_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    for module in ('test_agent_dependencies_consumers',):
        for name in GATE.REQUIRED_REGRESSION[module]:
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@functools.lru_cache(maxsize=1)
def tool_durable_runtime_fixture():
    with tempfile.TemporaryDirectory(prefix='dsh-tool-durable-source-') as folder:
        output = Path(folder) / 'paired.json'
        completed = subprocess.run([sys.executable, str(ROOT / 'scripts/tool_durable_oracle.py'),
            '--output', str(output)], cwd=str(ROOT), capture_output=True, timeout=240)
        if completed.returncode:
            raise RuntimeError(output.read_text(encoding='utf-8'))
        return dict(source=json.loads(output.with_suffix('.source.json').read_text(encoding='utf-8')),
            native=json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8')))

@pytest.mark.parametrize('damage', GATE.TOOL_DURABLE_DAMAGES + ('receipt-missing', 'source-missing', 'source-changed', 'source-file'))
def test_extracted_tool_durable_requires_complete_values_and_runtime(tmp_path, damage):
    archive, candidate, report = extracted_receipt(tmp_path)
    if damage == 'receipt-missing':
        del report['toolDurable']
    elif damage == 'source-missing':
        del candidate['tool_durable_source']
    elif damage == 'source-changed':
        candidate['tool_durable_source']['rows'][0]['calls'] = []
    elif damage == 'source-file':
        report['toolDurableSourceSha256'] = '0' * 64
    else:
        report['toolDurable'] = damage_tool_durable_runtime(report['toolDurable'], damage)
    output = tmp_path / 'extracted.json'
    output.write_text(json.dumps(report), encoding='utf-8')
    with pytest.raises(RuntimeError, match='toolDurable'):
        GATE.validate_extracted(output, archive, candidate)

@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_tool_durable_consumer_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    for module in ('test_tool_durable_consumers',):
        for name in GATE.REQUIRED_REGRESSION[module]:
            regression_xml(path, **{damage: (module, name)})
            with pytest.raises(RuntimeError):
                GATE.validate_regression(path)


@pytest.mark.parametrize('damage', ('omit', 'skip', 'duplicate', 'failure'))
def test_process_artifact_retention_lanes_are_mandatory(tmp_path, damage):
    path = tmp_path / 'pytest.xml'
    key = ('test_process_artifact_retention', sorted(GATE.REQUIRED_REGRESSION['test_process_artifact_retention'])[0])
    regression_xml(path, **{damage: key})
    with pytest.raises(RuntimeError):
        GATE.validate_regression(path)

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
