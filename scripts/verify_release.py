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
sys.path.insert(0, str(ROOT))
from scripts.mcp_stdio_oracle import validate_runtime_report as validate_mcp_runtime
from scripts.mcp_http_oracle import validate_runtime_report as validate_mcp_http_runtime
from scripts.acp_mcp_oracle import validate_process as validate_acp_mcp_process
from scripts.subagent_acp_oracle import validate_process as validate_subagent_acp_process
from scripts.subagent_acp_teardown_oracle import validate_runtime as validate_subagent_acp_teardown
from scripts.mcp_disposal_oracle import validate_runtime as validate_mcp_disposal
from scripts.subprocess_ownership_oracle import validate_runtime as validate_subprocess_ownership
from scripts.subprocess_tree_oracle import validate_observations as validate_subprocess_tree
from scripts.projection_cache_failure_oracle import validate_runtime as validate_projection_cache_reads
from scripts.session_observation_read_oracle import validate_runtime as validate_session_observation_reads
from scripts.session_corpus_list_oracle import validate_runtime as validate_session_corpus_list
from scripts.session_corpus_read_oracle import validate_runtime as validate_session_corpus_read
from scripts.session_lineage_oracle import validate_runtime as validate_session_lineage
from scripts.session_event_trace_oracle import validate_runtime as validate_session_event_trace
NODE_VERSION = 'v22.22.2'
PORTABLE_ARCHIVE = 'dist/dsh-win7-portable-v0.1.0.zip'
PAIRED_DRIVERS = (
    'agent_factory', 'agent_config', 'session_recovery', 'session_live',
    'session_prepared', 'session_storage', 'session_projection', 'deepseek',
    'pi', 'storage_cache', 'workflow_ralph', 'repeat_tool', 'token_meter',
    'pruner', 'compaction', 'maintenance', 'timeout_policy', 'abort',
    'approval', 'inspect', 'cordis_guard', 'cordis_runner',
    'cordis_retirement', 'cordis_tools', 'acp_sessions', 'acp_model_output', 'acp_stdio', 'acp_permissions', 'mcp_stdio', 'mcp_http', 'acp_mcp', 'subagent_acp', 'subagent_acp_teardown', 'mcp_disposal', 'subprocess_ownership', 'subprocess_tree', 'projection_cache_failure', 'session_observation_read', 'session_corpus_list', 'session_corpus_read', 'session_lineage', 'session_event_trace',
)
OFFICIAL_CONFIGS = ('consumers', 'agent-lifecycle', 'session-recovery', 'session-projection', 'acp', 'acp-app', 'mcp', 'subagent-acp', 'storage-cache', 'session-observation', 'session-corpus')
REQUIRED_REGRESSION = {
    'test_session_lineage_source': {'test_source_session_lineage_contract'},
    'test_session_event_trace_source': {'test_source_session_event_trace_contract'},
    'test_session_lineage': {
        name + '[' + backend + ']' for name in (
            'test_actual_durable_lineage_is_cold_ordered_and_marks_unresolved_parent',
            'test_actual_durable_lineage_pre_abort_uses_exact_reason_without_backend_access')
        for backend in ('jsonl', 'sqlite')},
    'test_session_event_trace': {
        'test_actual_durable_surface_event_trace_and_window_stay_cold_and_detached[' + backend + ']'
        for backend in ('jsonl', 'sqlite')},
    'test_session_corpus_read_source': {'test_actual_original_and_native_corpus_load_and_title_batch_signal_drain_and_source_ownership'},
    'test_session_corpus_read': {
        name + '[' + backend + ']' for name in (
            'test_actual_durable_corpus_load_and_title_batch_are_cold_detached_and_immutable',
            'test_actual_durable_title_batch_pre_abort_preserves_reason_without_listing')
        for backend in ('jsonl', 'sqlite')},
    'test_python_plugin_zip_staging': {
        'test_wrapped_zip_needs_no_post_extraction_subroot_rename[' + operation + ']'
        for operation in ('add', 'upgrade')},
    'test_session_corpus_list_source': {'test_actual_original_and_native_corpus_list_errors_signals_and_source_ownership'},
    'test_session_corpus_list': {
        name + '[' + backend + ']' for name in (
            'test_actual_durable_list_refuses_exact_pre_abort_before_backend_access',
            'test_actual_durable_list_keeps_live_precedence_and_detaches_returned_headers')
        for backend in ('jsonl', 'sqlite')},
    'test_session_observation_read_source': {'test_actual_original_and_native_point_read_failures_and_retained_cut_ownership'},
    'test_projection_cache_failure_source': {'test_actual_original_and_native_durable_cache_read_failure_and_prepared_fallback'},
    'test_subagent_acp_peer_encoding': {'test_acp_peer_reads_utf8_wire_without_inherited_python_encoding'},
    'test_subprocess_tree_source': {'test_actual_original_and_native_physical_windows_tree_lifecycle'},
    'test_subprocess_physical_tree': {'test_actual_owned_root_and_descendant_exit[' + name + ']' for name in ('direct', 'dispose', 'abort', 'terminate')},
    'test_subprocess_ownership_source': {'test_actual_original_subprocess_service_pending_exit_and_teardown_failure_ownership'},
    'test_mcp_disposal_source': {'test_actual_original_mcp_disposal_source_native_queue_and_factory_ownership'},
    'test_subagent_acp_teardown_source': {'test_actual_original_subprocess_acp_teardown_failure_aggregate_causes_and_identity'},
    'test_subagent_acp_dispose_cancellation': {
        'test_cancelled_dispose_awaiter_cannot_cancel_owned_eof_flush_and_process_reap',
        'test_cancelled_start_awaiter_reaps_unpublished_blocked_new_session_child'},
    'test_subagent_acp_source': {'test_actual_original_acp_subagent_runs_match_native_complete_public_observations'},
    'test_agent_signal_source': {'test_actual_original_model_tool_signal_generation_and_cancelled_admission_recover'},
    'test_subagent_acp_process': {'test_actual_parent_acp_subprocess_child_file_model_chain_and_reap'},
    'test_subagent_acp_signal': {'test_actual_agent_model_tool_signal_preserves_abort_reason_and_next_turn_generation'},
    'test_subagent_acp_consumer': {
        'test_canonical_profile_actual_tools_consumer_owns_acp_child_exit[' + backend + ']'
        for backend in ('jsonl', 'sqlite')
    },
    'test_subagent_acp': {
        'test_real_acp_child_output_protocol_and_terminal_reason[' + reason + '-' + expected + ']'
        for reason, expected in (('end_turn', 'completed'), ('max_tokens', 'max-tokens'),
            ('refusal', 'refusal'), ('cancelled', 'aborted'), ('max_turn_requests', 'error'))
    } | {
        'test_actual_permission_decision_is_safe_and_first_allow_selected[' + policy + '-' + no_allow + '-' + expected + ']'
        for policy, no_allow, expected in (('reject', 'False', 'denied'),
            ('allow', 'False', 'allowed'), ('allow', 'True', 'denied'))
    } | {'test_noncooperative_cancel_settles_partial_result_then_dispose_proves_exit',
         'test_eof_flush_and_explicit_credentials_use_owned_subprocess_seam',
         'test_startup_abort_rolls_back_unpublished_real_child',
         'test_safe_configuration_and_spawn_failure_do_not_leak_path',
         'test_provider_registration_is_reversible_and_rejects_parent_capabilities'},
    'test_acp_mcp_source': {'test_actual_acp_source_mcp_declarations_defaults_errors_and_prevalidation'},
    'test_acp_mcp_runtime_source': {'test_actual_source_and_native_acp_session_mcp_consumer_lifecycle'},
    'test_acp_mcp_abort_source': {'test_actual_source_and_native_mcp_startup_abort_wait_for_late_handshake_then_reap'},
    'test_acp_mcp_process': {'test_actual_acp_process_owns_stdio_http_session_tools_and_model_consumers'},
    'test_acp_mcp_runtime': {
        'test_actual_profile_session_mcp_tools_are_isolated_reaped_and_remounted[' + backend + ']'
        for backend in ('jsonl', 'sqlite')
    } | {'test_actual_profile_http_mcp_headers_and_tool_consumer_are_session_owned'} | {
        'test_actual_factory_rolls_back_all_mcp_children_before_agent_publication[' + failure + ']'
        for failure in ('invalid-declaration', 'missing-executable')
    } | {
        'test_cancelled_unpublished_mcp_setup_drains_real_child[' + reason + ']'
        for reason in ('request-abort', 'bridge-close')
    },
    'test_mcp_http_source': {'test_actual_source_http_sdk_wire_results_errors_and_close'},
    'test_mcp_supervisor_source': {'test_actual_source_supervisor_outcomes_logs_and_owned_registry_order'},
    'test_mcp_factory_source': {'test_actual_sdk_factory_failure_stops_at_the_close_barrier_without_retry'},
    'test_mcp_http_transport': {
        'test_actual_http_json_sse_and_explicit_session_termination[' + mode + ']'
        for mode in ('json', 'json-batch', 'json-bom', 'post-sse', 'sse-bom', 'get-sse', 'session', 'delete-405')
    } | {
        'test_actual_http_failure_cannot_invent_success[' + mode + ']'
        for mode in ('status-401', 'unexpected-content', 'missing-content', 'peer-error')
    } | {
        'test_actual_http_pending_cancel_timeout_and_close_reclaim_resources[' + mode + ']'
        for mode in ('cancel', 'timeout', 'close-pending')
    } | {'test_actual_http_plugin_activation_tools_consumer_and_scope_unload'},
    'test_mcp_schema': {'test_pinned_mcp_schemas_preserve_all_raw_source_parse_observations'},
    'test_mcp_config': {'test_actual_source_configuration_defaults_errors_and_raw_reconnect_resolution'},
    'test_mcp_tools_source': {'test_actual_source_bridge_text_names_and_exact_execution_refusal'},
    'test_mcp_image_consumer': {'test_real_stdio_image_tool_finalizes_durable_refs_and_cold_model_request'},
    'test_mcp_stdio_transport': {
        'test_actual_handshake_tools_correlation_notifications_and_scrubbed_environment',
        'test_invalid_negotiation_closes_actual_process_before_exposing_client',
    } | {
        'test_spawn_is_owned_before_await_and_late_process_is_reaped[' + reason + ']'
        for reason in ('dispose', 'cancel-connect')
    } | {
        'test_owned_pending_request_settles_and_late_work_cannot_survive_shutdown[' + reason + ']'
        for reason in ('close', 'cancel', 'timeout')
    },
    'test_mcp_supervisor': {'test_real_stdio_connection_registers_actual_tools_service_consumer'},
    'test_acp_permission_process': {
        'test_actual_permission_process_keeps_one_shot_tool_and_shutdown_ownership[' + mode + ']'
        for mode in ('allow', 'reject', 'malformed', 'cancel-late', 'close-late', 'eof')
    },
    'test_acp_stdio_journey': {
        'test_actual_acp_profile_stdio_output_and_new_process_durable_resume',
        'test_real_process_concurrent_sessions_cancel_only_owned_request[session/cancel]',
        'test_real_process_concurrent_sessions_cancel_only_owned_request[$/cancel_request]',
        'test_real_process_eof_cancels_active_turn_and_reopens_durable_session',
    },
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
            or report.get('acp', {}).get('processes') != 2
            or report.get('acp', {}).get('steps') != ['initialize-0', 'invalid-params-before-effects',
                'persistent-new', 'close-list-0', 'eof-0', 'initialize-1',
                'new-process-resume-no-history-updates', 'close-list-1', 'eof-1']
            or report.get('acpPermissions', {}).get('processes') != 6
            or report.get('acpPermissions', {}).get('modes') != ['allow', 'reject', 'malformed', 'cancel-late', 'close-late', 'eof']
            or len(report.get('acpPermissions', {}).get('observations', [])) != 6
            or report.get('frontendFilesChecked', 0) <= 0):
        raise RuntimeError('Extracted runtime/browser/ACP acceptance is incomplete')
    for row, mode in zip(report['acpPermissions']['observations'], report['acpPermissions']['modes']):
        expected = {'allow': 'allowed-once', 'reject': 'rejected', 'malformed': 'unavailable'}.get(mode, 'cancelled')
        audit = row.get('audit', [])
        if (row.get('mode') != mode or row.get('executed') is not (mode == 'allow') or row.get('stderr') != ['']
                or row.get('modelRequests') != (2 if mode in ('allow', 'reject', 'malformed') else 1)
                or [event.get('type') for event in audit] != ['approval/asked', 'approval/decided']
                or audit[0]['data'].get('id') != audit[1]['data'].get('id')
                or audit[1]['data'].get('outcome') != expected):
            raise RuntimeError('Extracted permission ownership/audit observations are incomplete')
    mcp = report.get('mcpStdio', {})
    try:
        validate_mcp_runtime(mcp)
    except ValueError as error:
        raise RuntimeError('Extracted MCP stdio observations are incomplete') from error
    try:
        validate_mcp_http_runtime(report.get('mcpHttp', {}))
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted MCP HTTP observations are incomplete') from error
    try:
        validate_acp_mcp_process(report.get('acpMcp'))
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted ACP MCP process observations are incomplete') from error
    try:
        validate_subagent_acp_process(report.get('subagentAcp'))
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted subprocess ACP file/model observations are incomplete') from error
    try:
        validate_subagent_acp_teardown(report.get('subagentAcpTeardown'))
        if report['subagentAcpTeardown']['root'] != report['mcpStdio']['root']:
            raise ValueError('Subprocess ACP teardown came from a different runtime')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted subprocess ACP teardown observations are incomplete') from error
    try:
        validate_mcp_disposal(report.get('mcpDisposal'))
        if report['mcpDisposal']['root'] != report['mcpStdio']['root']:
            raise ValueError('MCP disposal came from a different runtime')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted MCP disposal observations are incomplete') from error
    try:
        validate_subprocess_ownership(report.get('subprocessOwnership'))
        if report['subprocessOwnership']['root'] != report['mcpStdio']['root']:
            raise ValueError('Subprocess ownership came from a different runtime')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted subprocess ownership observations are incomplete') from error
    try:
        validate_subprocess_tree(report.get('subprocessTree'), Path(report['mcpStdio']['root']))
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted physical subprocess tree observations are incomplete') from error
    try:
        validate_projection_cache_reads(report.get('projectionCacheReads'))
        if report['projectionCacheReads']['root'] != report['mcpStdio']['root']:
            raise ValueError('Projection cache reads came from a different runtime')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted projection cache read observations are incomplete') from error
    try:
        validate_session_observation_reads(report.get('sessionObservationReads'))
        if report['sessionObservationReads']['root'] != report['mcpStdio']['root']:
            raise ValueError('Session observation reads came from a different runtime')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted Session observation read observations are incomplete') from error
    try:
        validate_session_corpus_list(report.get('sessionCorpusList'))
        if report['sessionCorpusList']['root'] != report['mcpStdio']['root']:
            raise ValueError('Session corpus listing came from a different runtime')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted Session corpus listing observations are incomplete') from error
    try:
        validate_session_corpus_read(report.get('sessionCorpusRead'))
        if report['sessionCorpusRead']['root'] != report['mcpStdio']['root']:
            raise ValueError('Session corpus reads came from a different runtime')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted Session corpus read observations are incomplete') from error
    for name, validate in [('sessionLineage', validate_session_lineage), ('sessionEventTrace', validate_session_event_trace)]:
        try:
            validate(report.get(name))
            if report[name]['root'] != report['mcpStdio']['root']:
                raise ValueError('Session tracing came from a different runtime')
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError('Extracted ' + name + ' observations are incomplete') from error
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
    run([python, '-m', 'pytest', 'tests', '-ra', '--junitxml=' + str(regression),
         '--basetemp=' + str(output / 'pytest-workspace')],
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
