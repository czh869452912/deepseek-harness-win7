import argparse
import copy
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from scripts.mcp_stdio_oracle import MODES as MCP_MODES, expected_row as mcp_expected_row
from scripts.mcp_http_oracle import EXPECTED as HTTP_EXPECTED
from scripts.subagent_acp_oracle import expected_process as expected_subagent_acp_process


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


def test_regression_requires_browser_portable_and_acp_process_lanes(tmp_path):
    path = tmp_path / 'pytest.xml'
    regression_xml(path)
    assert GATE.validate_regression(path) == {'required_lanes': 81, 'skipped': 1}


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


def extracted_receipt(tmp_path):
    archive = tmp_path / 'portable.zip'
    archive.write_bytes(b'exact candidate archive')
    candidate = {'product_commit': 'a' * 40, 'worktree_dirty': False}
    report = {'result': 'passed', 'browser': {'passed': True}, 'runtime': {'checks': ['actual runtime']},
              'acp': {'processes': 2, 'steps': ['initialize-0', 'invalid-params-before-effects',
                  'persistent-new', 'close-list-0', 'eof-0', 'initialize-1',
                  'new-process-resume-no-history-updates', 'close-list-1', 'eof-1']},
              'runtimeStderr': '', 'frontendFilesChecked': 119, 'archive': str(archive),
              'archiveSha256': GATE.digest(archive), 'provenance': dict(candidate)}
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
    report['subagentAcp'] = expected_subagent_acp_process()
    return archive, candidate, report


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
    assert {'acp_sessions', 'acp_model_output', 'acp_stdio', 'acp_permissions', 'mcp_stdio', 'mcp_http', 'acp_mcp', 'subagent_acp'} <= set(GATE.PAIRED_DRIVERS)
    assert {'acp', 'acp-app', 'mcp', 'subagent-acp'} <= set(GATE.OFFICIAL_CONFIGS)
    assert {'deepseek', 'pi', 'compaction', 'approval', 'cordis_retirement', 'workflow_ralph', 'pruner'} <= set(GATE.PAIRED_DRIVERS)
    assert len(GATE.PAIRED_DRIVERS) == len(set(GATE.PAIRED_DRIVERS))
    workflow = (ROOT / '.github/workflows/verify.yml').read_text(encoding='utf-8')
    assert '--browser $browser' in workflow
    assert '${{ steps.gate.outputs.archive }}' in workflow
    assert 'archive_sha256' in workflow and 'publishable' in workflow


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
    'test_subagent_acp_process', 'test_subagent_acp_signal', 'test_subagent_acp_consumer', 'test_subagent_acp'])
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
