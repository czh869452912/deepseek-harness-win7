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
import signal
import subprocess
import sys
import tempfile
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
from scripts.session_filters_oracle import validate_runtime as validate_session_filters
from scripts.session_requests_oracle import validate_runtime as validate_session_requests
from scripts.webserver_reset_probe import validate as validate_webserver_reset
from scripts.python_directory_probe import validate as validate_python_directory
from scripts.session_snapshots_oracle import validate_runtime as validate_session_snapshots
from scripts.query_schema_oracle import validate_runtime as validate_query_schema
from scripts.query_engine_oracle import validate_runtime as validate_query_engine
from scripts.query_unicode_oracle import validate_runtime as validate_query_unicode, source_identity as unicode_source_identity
from scripts.session_text_oracle import validate_runtime as validate_session_text, source_identity as text_source_identity
from scripts.session_tools_oracle import validate_runtime as validate_session_tools, source_identity as tools_source_identity, module_hashes as tools_module_hashes
from scripts.sqlite_format_oracle import validate_runtime as validate_sqlite_format, source_identity as format_source_identity, module_hashes as format_module_hashes, asset_hashes as format_asset_hashes
from scripts.sqlite_provider_oracle import validate_runtime as validate_sqlite_provider, source_identity as provider_source_identity, hashes as provider_hashes, MODULES as PROVIDER_MODULES, ASSETS as PROVIDER_ASSETS
from scripts.jsonl_provider_oracle import validate_runtime as validate_jsonl_provider, source_identity as jsonl_source_identity, MODULES as JSONL_MODULES, ASSETS as JSONL_ASSETS
from scripts.tool_scheduler_oracle import validate_runtime as validate_tool_scheduler, identity as scheduler_identity
from scripts.http_redirect_oracle import NAMES as REDIRECT_NAMES, validate_runtime as validate_http_redirect, identity as redirect_identity
from scripts.javascript_workflow_oracle import validate_runtime as validate_javascript_workflow, identity as javascript_identity
from scripts.runtime_context_oracle import validate_runtime as validate_runtime_context, identity as runtime_context_identity
from scripts.javascript_ready_oracle import validate_runtime as validate_javascript_ready, identity as ready_identity
from scripts.javascript_initial_oracle import validate_runtime as validate_javascript_initial, identity as initial_identity, NAMES as INITIAL_NAMES
from scripts.session_number_oracle import validate_runtime as validate_session_number, identity as number_identity, NAMES as NUMBER_NAMES
from scripts.session_diagnostic_oracle import validate_runtime as validate_session_diagnostic, identity as diagnostic_identity, NAMES as DIAGNOSTIC_NAMES
from scripts.session_restore_sign_oracle import validate_runtime as validate_session_restore_sign, identity as restore_sign_identity, NAMES as RESTORE_SIGN_NAMES
from scripts.runtime_full_request_oracle import validate_runtime as validate_runtime_full_request, identity as full_request_identity, NAMES as FULL_REQUEST_NAMES
from scripts.deepseek_error_oracle import validate_runtime as validate_deepseek_error, identity as deepseek_error_identity, NAMES as DEEPSEEK_ERROR_NAMES
from scripts.deepseek_capture_oracle import validate_runtime as validate_deepseek_capture, identity as deepseek_capture_identity, NAMES as DEEPSEEK_CAPTURE_NAMES
from scripts.persistence_read_oracle import validate_runtime as validate_persistence_read, identity as read_identity, NAMES as READ_NAMES
from scripts.jsonl_sharing_oracle import validate_runtime as validate_jsonl_sharing, identity as sharing_identity, NAMES as SHARING_NAMES
from scripts.canonical_llm_oracle import validate_runtime as validate_canonical_llm, identity as canonical_llm_identity, NAMES as CANONICAL_LLM_NAMES
from scripts.llm_prepared_oracle import validate_runtime as validate_llm_prepared, identity as llm_prepared_identity, NAMES as LLM_PREPARED_NAMES
from scripts.llm_metadata_oracle import validate_runtime as validate_llm_metadata, identity as llm_metadata_identity, NAMES as LLM_METADATA_NAMES
from scripts.process_artifact_retention import prune_previous_regressions, prune_finished_focus_runs, expire_finished_manifests
NODE_VERSION = 'v22.22.2'
PORTABLE_ARCHIVE = 'dist/dsh-win7-portable-v0.1.0.zip'
PAIRED_DRIVERS = (
    'agent_factory', 'agent_config', 'session_recovery', 'session_live',
    'session_prepared', 'session_storage', 'session_projection', 'deepseek',
    'pi', 'storage_cache', 'workflow_ralph', 'repeat_tool', 'token_meter',
    'pruner', 'compaction', 'maintenance', 'timeout_policy', 'abort',
    'approval', 'inspect', 'cordis_guard', 'cordis_runner',
    'cordis_retirement', 'cordis_tools', 'acp_sessions', 'acp_model_output', 'acp_stdio', 'acp_permissions', 'mcp_stdio', 'mcp_http', 'acp_mcp', 'subagent_acp', 'subagent_acp_teardown', 'mcp_disposal', 'subprocess_ownership', 'subprocess_tree', 'projection_cache_failure', 'session_observation_read', 'session_corpus_list', 'session_corpus_read', 'session_lineage', 'session_event_trace', 'session_filters', 'session_requests', 'session_snapshots', 'query_schema', 'query_engine', 'query_unicode', 'session_text',
)
PAIRED_DRIVERS = PAIRED_DRIVERS + ('session_tools', 'sqlite_format', 'sqlite_provider', 'jsonl_provider', 'tool_scheduler', 'http_redirect', 'javascript_workflow', 'runtime_context', 'javascript_ready', 'persistence_read')
PAIRED_DRIVERS = PAIRED_DRIVERS + ('javascript_initial', 'session_number', 'session_diagnostic', 'session_restore_sign')
PAIRED_DRIVERS = PAIRED_DRIVERS + ('runtime_full_request', 'deepseek_error', 'deepseek_capture', 'jsonl_sharing', 'canonical_llm', 'llm_metadata', 'llm_prepared')
OFFICIAL_CONFIGS = ('consumers', 'agent-lifecycle', 'session-recovery', 'session-projection', 'acp', 'acp-app', 'mcp', 'subagent-acp', 'storage-cache', 'session-observation', 'session-corpus', 'session-sqlite-query', 'query-engine-source', 'session-tools-source', 'sqlite-format-source', 'sqlite-provider-source', 'jsonl-provider-source', 'tool-scheduler-source', 'deepseek-source', 'llm-public-source')
REQUIRED_REGRESSION = {
    'test_process_artifact_retention': {
        'test_active_or_unowned_workspaces_are_refused[active]',
        'test_active_or_unowned_workspaces_are_refused[foreign-execution]',
        'test_active_or_unowned_workspaces_are_refused[foreign-retained]',
        'test_active_or_unowned_workspaces_are_refused[incomplete-xml]',
        'test_active_or_unowned_workspaces_are_refused[missing-xml]',
        'test_actual_cli_keeps_real_files_and_prunes_completed_receipts[output]',
        'test_actual_cli_keeps_real_files_and_prunes_completed_receipts[previous]',
        'test_actual_pytest_end_hook_prunes_synthetic_data_and_preserves_diagnostics[failed]',
        'test_actual_pytest_end_hook_prunes_synthetic_data_and_preserves_diagnostics[passed]',
        'test_audit_examples_are_bounded',
        'test_changed_file_is_preserved_and_partial_failure_is_audited',
        'test_expired_cleanup_manifests_keep_latest_two_and_pending_data',
        'test_finished_synthetic_receipts_are_pruned_with_bounded_audit[extracted.json]',
        'test_finished_synthetic_receipts_are_pruned_with_bounded_audit[receipt.json]',
        'test_focused_results_require_finished_log_and_complete_xml[active]',
        'test_focused_results_require_finished_log_and_complete_xml[finished]',
        'test_focused_results_require_finished_log_and_complete_xml[partial-xml]',
        'test_junction_or_symlink_never_deletes_foreign_receipts',
        'test_missing_runtime_negative_fixture_is_still_synthetic',
        'test_startup_cleanup_ignores_unfinished_outputs',
        'test_unclassified_cleanup_manifests_are_preserved[count]',
        'test_unclassified_cleanup_manifests_are_preserved[invalid-json]',
        'test_unclassified_cleanup_manifests_are_preserved[outside]',
        'test_unclassified_cleanup_manifests_are_preserved[root-list]',
        'test_unclassified_cleanup_manifests_are_preserved[unknown-name]',
        'test_unclassified_or_real_artifacts_are_preserved[foreign-runtime]',
        'test_unclassified_or_real_artifacts_are_preserved[invalid-json]',
        'test_unclassified_or_real_artifacts_are_preserved[missing-runtime]',
        'test_unclassified_or_real_artifacts_are_preserved[nested-folder]',
        'test_unclassified_or_real_artifacts_are_preserved[real-zip]',
        'test_unclassified_or_real_artifacts_are_preserved[unknown-name]',
        'test_unclassified_or_real_artifacts_are_preserved[unowned-folder]',
        'test_unfinished_pytest_sessions_are_not_pruned[2]',
        'test_unfinished_pytest_sessions_are_not_pruned[3]',
        'test_unfinished_pytest_sessions_are_not_pruned[4]',
        'test_unfinished_pytest_sessions_are_not_pruned[5]',
        'test_unfinished_pytest_sessions_are_not_pruned[False]',
    },
    'test_llm_prepared_consumers': {
        *{'test_actual_original_and_native_llm_prepared_match[' + name + ']' for name in LLM_PREPARED_NAMES},
        *{'test_llm_prepared_requires_complete_values_and_runtime[' + damage + ']' for damage in ('config', 'boolean', 'defaults', 'context', 'error', 'dispatch', 'trace', 'replay', 'signal', 'frozen', 'header', 'empty', 'message-form', 'message-split', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'bytes', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module')},
        *{'test_llm_prepared_source_identity_is_required[' + damage + ']' for damage in ('pin','node','inputs','bytes')},
        'test_llm_prepared_source_message_identity_retains_uuid_shape',
        *{'test_portable_llm_prepared_refuses_partial_receipts[' + side + ']' for side in ('source','native')},
    },
    'test_llm_metadata_consumers': {
        *{'test_actual_original_and_native_llm_metadata_match[' + name + ']' for name in LLM_METADATA_NAMES},
        *{'test_llm_metadata_requires_complete_values_and_runtime[' + damage + ']' for damage in ('model', 'context', 'reasoning', 'description', 'max-tokens', 'modalities', 'trace', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'bytes', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module')},
        *{'test_llm_metadata_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_portable_llm_metadata_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
    },

    'test_canonical_llm_consumers': {
        *{'test_actual_original_and_native_canonical_llm_match[' + name + ']' for name in CANONICAL_LLM_NAMES},
        *{'test_canonical_llm_requires_complete_values_identity_and_runtime[' + damage + ']' for damage in ('request', 'event', 'tool-id', 'message-form', 'message-split', 'message-cross-fixture', 'retry-form', 'retry-split', 'retry-cross-fixture', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'bytes', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module')},
        *{'test_canonical_llm_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_portable_canonical_llm_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
        'test_literal_identity_marker_remains_a_literal_value',
        'test_source_message_identity_retains_uuid_shape',
    },

    'test_jsonl_sharing_consumers': {
        *{'test_actual_original_and_native_jsonl_shared_readers_match[' + name + ']' for name in SHARING_NAMES},
        *{'test_jsonl_sharing_receipt_requires_complete_values_and_runtime[' + damage + ']' for damage in (
            'header', 'event', 'raw', 'filename', 'tail', 'duplicate', 'order', 'root', 'python', 'executable', 'module', 'bytes')},
        *{'test_jsonl_sharing_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_portable_jsonl_sharing_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
        'test_real_exclusive_holder_remains_a_sharing_error',
        'test_reader_close_releases_actual_handle_for_exclusive_owner',
        'test_missing_shared_reader_stays_file_not_found',
        'test_shared_reader_handles_long_owned_paths',
    },
    'test_deepseek_capture_consumers': {
        *{'test_actual_deepseek_capture_matches_source[' + name + ']' for name in DEEPSEEK_CAPTURE_NAMES},
        *{'test_deepseek_capture_receipt_requires_complete_rows_and_runtime[' + damage + ']' for damage in ('config-name', 'config-message', 'error-name', 'error-message', 'failure-message', 'error-code', 'file-message', 'file-failure', 'file-quota', 'file-status', 'settings-model', 'settings-provider', 'settings-retry', 'stream', 'serialization', 'usage', 'request-body', 'accepted', 'origin', 'retry-failure', 'retry-delay', 'retry-policy', 'retry-number', 'retry-split', 'retry-shared', 'retry-form', 'tail', 'duplicate', 'root', 'python', 'executable', 'module', 'bytes')},
        *{'test_deepseek_capture_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        'test_actual_retry_ids_may_change_without_splitting_or_merging_chains',
        *{'test_actual_loopback_origin_keeps_listener_and_endpoint_relation[' + mode + ']' for mode in ('renamed', 'host', 'configured', 'bool')},
        *{'test_portable_deepseek_capture_cli_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
    },
    'test_deepseek_error_consumers': {
        *{'test_actual_deepseek_complete_http_failures_match_source[' + name + ']' for name in DEEPSEEK_ERROR_NAMES},
        *{'test_deepseek_error_receipt_requires_complete_rows_and_runtime[' + damage + ']' for damage in (
            'error-name', 'error-message', 'failure-message', 'error-code', 'status', 'retry-after',
            'request-id', 'preview', 'surrogate', 'timer', 'fraction', 'chunk', 'request-body',
            'tail', 'duplicate', 'root', 'python', 'executable', 'module', 'bytes')},
        *{'test_deepseek_error_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_actual_retry_hint_keeps_json_numeric_value[' + spelling + ']' for spelling in ('native-float', 'source-float', 'fraction')},
        *{'test_portable_deepseek_error_cli_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
    },
    'test_release_workspace': {
        'test_retention_error_never_hides_primary_regression_failure[passed]',
        'test_retention_error_never_hides_primary_regression_failure[failed]',
        'test_actual_release_process_preserves_exit_status_and_logs[0]',
        'test_actual_release_process_preserves_exit_status_and_logs[7]',
        'test_actual_timeout_retires_redirector_descendants_before_workspace_move',
        'test_short_pytest_workspace_retains_owned_success_and_failure_artifacts[passed]',
        'test_short_pytest_workspace_retains_owned_success_and_failure_artifacts[failed]',
        'test_short_pytest_workspace_runs_actual_shared_checkpoint_git_consumer',
    },
    'test_runtime_full_request_consumers': {
        *{'test_actual_complete_agent_model_requests_match_source[' + name + ']' for name in FULL_REQUEST_NAMES},
        *{'test_full_request_receipt_requires_complete_graph_and_runtime[' + damage + ']' for damage in (
            'provider', 'system', 'tools', 'assistant-alias', 'token-alias', 'reasoning-alias',
            'message-owner', 'signal-owner', 'signal-state', 'tail', 'duplicate', 'root', 'python', 'executable', 'module', 'bytes')},
        *{'test_full_request_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_portable_full_request_cli_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
        *{'test_actual_fixed_parameter_adapter_keeps_python_boundary_arguments[' + configuration + ']' for configuration in ('max-tokens', 'reasoning', 'both')},
    },
    'test_session_restore_sign_consumers': {
        *{'test_actual_public_session_restore_numeric_values_match_source[' + name + ']' for name in RESTORE_SIGN_NAMES},
        *{'test_session_restore_sign_receipt_requires_numeric_identity_and_runtime[' + damage + ']' for damage in (
            'accepted', 'signed-zero', 'input-value', 'safe-integer', 'error-text',
            'missing-case', 'duplicate', 'root', 'python', 'executable', 'module', 'module-bytes')},
        *{'test_session_restore_sign_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_portable_restore_sign_cli_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
        *{'test_restored_header_signed_zero_survives_public_consumers[' + consumer + '-' + field + '-' + attribute + ']' for consumer in ('attribute', 'copy', 'deepcopy', 'export')
            for field, attribute in (('version', 'version'), ('createdAt', 'created_at'), ('seedLength', 'seed_length'), ('delegationDepth', 'delegation_depth'))},
    },
    'test_session_diagnostic_consumers': {
        *{'test_actual_public_session_admission_diagnostics_match_source[' + name + ']' for name in DIAGNOSTIC_NAMES},
        *{'test_session_diagnostic_receipt_requires_exact_errors_and_runtime[' + damage + ']' for damage in (
            'accepted', 'error-name', 'error-text', 'lossless-first', 'restore-negative-zero',
            'missing-case', 'duplicate', 'root', 'python', 'executable', 'module', 'module-bytes')},
        *{'test_session_diagnostic_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_portable_diagnostic_cli_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
    },
    'test_session_number_consumers': {
        *{'test_actual_public_session_number_and_frozen_metadata_match_source[' + name + ']' for name in NUMBER_NAMES},
        *{'test_session_number_receipt_requires_complete_metadata_and_runtime[' + damage + ']' for damage in (
            'outcome', 'header-field', 'header-mutation', 'nested-mutation', 'input-mutation',
            'clone-missing', 'clone-deep', 'clone-shallow', 'clone-original',
            'missing-case', 'duplicate', 'root', 'python', 'executable', 'module', 'module-bytes')},
        *{'test_session_number_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_portable_number_cli_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
        *{'test_published_header_copies_and_exports_preserve_source_ownership[' + action + ']' for action in ('copy', 'deepcopy', 'export', 'delete')},
    },
    'test_javascript_initial_consumers': {
        *{'test_actual_entry_exit_precedes_initial_write_failure[' + name + ']' for name in INITIAL_NAMES},
        *{'test_initial_receipt_requires_complete_outcome_and_ownership[' + damage + ']' for damage in (
            'outcome', 'cancel', 'late-event', 'child', 'exit', 'admitted', 'entry', 'emission', 'first',
            'disposed', 'tail', 'duplicate', 'root', 'python', 'executable', 'module', 'bytes', 'asset-missing', 'asset-bytes')},
        *{'test_initial_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        *{'test_portable_initial_cli_refuses_partial_receipts[' + side + ']' for side in ('source', 'native')},
        *{'test_live_initial_pipe_failure_keeps_original_identity[' + error + ']' for error in ('BrokenPipeError', 'ConnectionResetError')},
        *{'test_exited_initial_pipe_failure_uses_recorded_physical_outcome[' + error + ']' for error in ('BrokenPipeError', 'ConnectionResetError')},
    },
    'test_persistence_read_consumers': {
        *{'test_actual_canonical_persistence_numeric_and_cancelled_reads_match_source[' + name + ']' for name in READ_NAMES},
        *{'test_persistence_read_receipt_refuses_lost_semantics_and_foreign_runtime[' + damage + ']' for damage in (
            'outcome', 'signal', 'after-read', 'queue', 'legacy', 'cancel-priority', 'reason', 'missing-case',
            'duplicate', 'root', 'python', 'executable', 'module', 'module-bytes', 'asset-bytes')},
        *{'test_persistence_read_source_identity_is_required[' + damage + ']' for damage in ('pin', 'node', 'inputs', 'bytes')},
        'test_portable_read_cli_refuses_partial_receipts[source]',
        'test_portable_read_cli_refuses_partial_receipts[native]',
    },
    'test_runtime_observer_interpreter_identity': {
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-context]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-ready]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-workflow]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-read]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-initial]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-number]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-diagnostic]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-restore-sign]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-full-request]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-deepseek-error]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[selected-deepseek-capture]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-context]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-ready]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-workflow]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-read]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-initial]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-number]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-diagnostic]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-restore-sign]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-full-request]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-deepseek-error]',
        'test_unselected_in_tree_interpreter_is_refused_even_with_identical_bytes[extracted-deepseek-capture]',
    },
    "test_javascript_ready_consumers": {
        "test_actual_held_ready_crosses_exit_before_admission[held-ready-exit]",
        "test_actual_held_ready_crosses_exit_before_admission[cancel-before-held-ready-exit]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[outcome]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[cancel]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[late-event]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[child]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[exit]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[admitted]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[first]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[disposed]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[tail]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[duplicate]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[root]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[python]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[executable]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[module]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[bytes]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[asset-missing]",
        "test_ready_receipt_requires_complete_outcome_and_ownership[asset-bytes]",
        "test_ready_source_identity_is_required[pin]",
        "test_ready_source_identity_is_required[node]",
        "test_ready_source_identity_is_required[inputs]",
        "test_ready_source_identity_is_required[bytes]",
        "test_portable_ready_cli_refuses_partial_receipts[source]",
        "test_portable_ready_cli_refuses_partial_receipts[native]",
    },
    "test_http_redirect_fixture_lifetime": {"test_actual_redirect_fixture_never_sends_empty_response_body"},
    "test_runtime_context_consumers": {
        "test_model_tool_next_step_retains_complete_attributed_context[change]",
        "test_model_tool_next_step_retains_complete_attributed_context[clear]",
        "test_model_tool_next_step_retains_complete_attributed_context[same]",
        "test_model_tool_next_step_retains_complete_attributed_context[empty]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[attribution]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[second-step]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[clear]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[unchanged-duplicate]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[identity-correlation]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[snapshot]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[missing-request]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[missing-case]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[duplicate]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[root]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[python]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[executable]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[module]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[module-path]",
        "test_runtime_context_receipt_rejects_lost_messages_or_foreign_runtime[module-bytes]",
        "test_runtime_context_source_identity_is_required[pin]",
        "test_runtime_context_source_identity_is_required[node]",
        "test_runtime_context_source_identity_is_required[inputs]",
        "test_runtime_context_source_identity_is_required[guard-bytes]",
    },
    "test_javascript_runtime": {
        "test_actual_process_exit_remains_distinct_from_protocol_failure[exit]",
        "test_actual_process_exit_remains_distinct_from_protocol_failure[protocol]",
        "test_actual_engine_executes_language_promises_and_two_realms[closure-loop]",
        "test_actual_engine_executes_language_promises_and_two_realms[host-realm]",
        "test_actual_engine_executes_language_promises_and_two_realms[large-result]",
        "test_actual_engine_executes_language_promises_and_two_realms[promise-await]",
        "test_actual_engine_executes_language_promises_and_two_realms[unicode-language]",
        "test_build_refuses_unpinned_or_injected_archive_inputs[archive-bytes]",
        "test_build_refuses_unpinned_or_injected_archive_inputs[extra-header]",
        "test_build_refuses_unpinned_or_injected_archive_inputs[extracted-bytes]",
        "test_build_refuses_unpinned_or_injected_archive_inputs[traversal]",
        "test_build_refuses_unpinned_or_injected_archive_inputs[wrong-prefix]",
        "test_cancel_during_spawn_waits_for_owned_process_cleanup",
        "test_initial_cpu_slice_is_interrupted_without_blocking_host_loop",
        "test_modified_private_resource_is_refused_before_execution[MinGW-COPYING.winpthreads.txt]",
        "test_modified_private_resource_is_refused_before_execution[QUICKJS-NOTICES.txt]",
        "test_modified_private_resource_is_refused_before_execution[build-provenance.json]",
        "test_modified_private_resource_is_refused_before_execution[dsh_js_worker.exe]",
        "test_modified_private_resource_is_refused_before_execution[runtime.json]",
        "test_only_source_worker_temp_environment_is_forwarded",
        "test_parser_compiles_without_executing[for(;;){}]",
        "test_parser_compiles_without_executing[return {value:await Promise.resolve(7)}]",
        "test_parser_compiles_without_executing[throw new Error(\"not executed\")]",
        "test_provider_unload_owns_late_spawn_and_refuses_new_work",
        "test_startup_cancel_does_not_execute_body_and_disposal_is_shared",
        "test_unsettled_async_body_is_physically_terminated_on_owner_unload[await Promise.resolve(); for(;;){}]",
        "test_unsettled_async_body_is_physically_terminated_on_owner_unload[await new Promise(()=>{})]",
    },
    "test_javascript_workflow_session": {
        "test_actual_source_session_child_rpc_and_retained_process[death-before-provider-publication]",
        "test_actual_source_session_child_rpc_and_retained_process[death-after-child-publication]",
        "test_actual_source_session_child_rpc_and_retained_process[death-after-result]",
        "test_actual_source_session_child_rpc_and_retained_process[cancel-before-process-death]",
        "test_actual_source_session_child_rpc_and_retained_process[active-child-cancel]",
        "test_actual_source_session_child_rpc_and_retained_process[bad-option]",
        "test_actual_source_session_child_rpc_and_retained_process[bad-parallel]",
        "test_actual_source_session_child_rpc_and_retained_process[bad-pipeline]",
        "test_actual_source_session_child_rpc_and_retained_process[bad-prompt]",
        "test_actual_source_session_child_rpc_and_retained_process[bad-schema-exotic]",
        "test_actual_source_session_child_rpc_and_retained_process[bad-schema]",
        "test_actual_source_session_child_rpc_and_retained_process[child-blocks]",
        "test_actual_source_session_child_rpc_and_retained_process[child-route]",
        "test_actual_source_session_child_rpc_and_retained_process[child-schema]",
        "test_actual_source_session_child_rpc_and_retained_process[child-stop-failed]",
        "test_actual_source_session_child_rpc_and_retained_process[child-text]",
        "test_actual_source_session_child_rpc_and_retained_process[child-total-cap]",
        "test_actual_source_session_child_rpc_and_retained_process[child-unhonored-schema]",
        "test_actual_source_session_child_rpc_and_retained_process[dropped-child-after-result]",
        "test_actual_source_session_child_rpc_and_retained_process[dropped-child-continuation]",
        "test_actual_source_session_child_rpc_and_retained_process[empty-combinators]",
        "test_actual_source_session_child_rpc_and_retained_process[host-intrinsic-string]",
        "test_actual_source_session_child_rpc_and_retained_process[host-realm-schema]",
        "test_actual_source_session_child_rpc_and_retained_process[intrinsic-descriptor]",
        "test_actual_source_session_child_rpc_and_retained_process[intrinsic-strings]",
        "test_actual_source_session_child_rpc_and_retained_process[item-cap]",
        "test_actual_source_session_child_rpc_and_retained_process[parallel-children]",
        "test_actual_source_session_child_rpc_and_retained_process[parallel-ordinary-failure]",
        "test_actual_source_session_child_rpc_and_retained_process[pipeline-children]",
        "test_actual_source_session_child_rpc_and_retained_process[pipeline-ordinary-failure]",
        "test_actual_source_session_child_rpc_and_retained_process[pre-go-cancel]",
        "test_actual_source_session_child_rpc_and_retained_process[renamed-intrinsic-schema]",
        "test_actual_source_session_child_rpc_and_retained_process[signed-zero]",
        "test_actual_source_session_child_rpc_and_retained_process[spoof-intrinsic-schema]",
        "test_corrupt_source_session_resources_are_refused[SOURCE-LICENSE]",
        "test_corrupt_source_session_resources_are_refused[build-provenance.json]",
        "test_corrupt_source_session_resources_are_refused[driver.js]",
        "test_corrupt_source_session_resources_are_refused[source.js]",
        "test_corrupt_source_session_resources_are_refused[workflow.json]",
        "test_owner_unload_physically_terminates_unsettled_source_session",
    },
    "test_javascript_workflow_host": {
        "test_workflow_engine_actual_source_host_events_and_children[death-before-provider-publication]",
        "test_workflow_engine_actual_source_host_events_and_children[death-after-child-publication]",
        "test_workflow_engine_actual_source_host_events_and_children[death-after-result]",
        "test_workflow_engine_actual_source_host_events_and_children[cancel-before-process-death]",
        "test_workflow_engine_actual_source_host_events_and_children[active-child-cancel]",
        "test_workflow_engine_actual_source_host_events_and_children[bad-option]",
        "test_workflow_engine_actual_source_host_events_and_children[bad-parallel]",
        "test_workflow_engine_actual_source_host_events_and_children[bad-pipeline]",
        "test_workflow_engine_actual_source_host_events_and_children[bad-prompt]",
        "test_workflow_engine_actual_source_host_events_and_children[bad-schema-exotic]",
        "test_workflow_engine_actual_source_host_events_and_children[bad-schema]",
        "test_workflow_engine_actual_source_host_events_and_children[child-blocks]",
        "test_workflow_engine_actual_source_host_events_and_children[child-route]",
        "test_workflow_engine_actual_source_host_events_and_children[child-schema]",
        "test_workflow_engine_actual_source_host_events_and_children[child-stop-failed]",
        "test_workflow_engine_actual_source_host_events_and_children[child-text]",
        "test_workflow_engine_actual_source_host_events_and_children[child-total-cap]",
        "test_workflow_engine_actual_source_host_events_and_children[child-unhonored-schema]",
        "test_workflow_engine_actual_source_host_events_and_children[dropped-child-after-result]",
        "test_workflow_engine_actual_source_host_events_and_children[dropped-child-continuation]",
        "test_workflow_engine_actual_source_host_events_and_children[empty-combinators]",
        "test_workflow_engine_actual_source_host_events_and_children[host-intrinsic-string]",
        "test_workflow_engine_actual_source_host_events_and_children[host-realm-schema]",
        "test_workflow_engine_actual_source_host_events_and_children[intrinsic-descriptor]",
        "test_workflow_engine_actual_source_host_events_and_children[intrinsic-strings]",
        "test_workflow_engine_actual_source_host_events_and_children[item-cap]",
        "test_workflow_engine_actual_source_host_events_and_children[parallel-children]",
        "test_workflow_engine_actual_source_host_events_and_children[parallel-ordinary-failure]",
        "test_workflow_engine_actual_source_host_events_and_children[pipeline-children]",
        "test_workflow_engine_actual_source_host_events_and_children[pipeline-ordinary-failure]",
        "test_workflow_engine_actual_source_host_events_and_children[pre-go-cancel]",
        "test_workflow_engine_actual_source_host_events_and_children[renamed-intrinsic-schema]",
        "test_workflow_engine_actual_source_host_events_and_children[signed-zero]",
        "test_workflow_engine_actual_source_host_events_and_children[spoof-intrinsic-schema]",
    },
    "test_javascript_workflow_consumers": {
        "test_cancellation_grace_physically_terminates_unsettled_script[await Promise.resolve();for(;;){}]",
        "test_cancellation_grace_physically_terminates_unsettled_script[await new Promise(()=>{})]",
        "test_held_javascript_run_starts_and_disposes_children_after_engine_unload",
        "test_late_provider_is_refused_before_slow_disposal_finishes",
        "test_missing_args_remain_javascript_undefined",
        "test_original_ralph_script_executes_without_native_translation[reports0-complete]",
        "test_original_ralph_script_executes_without_native_translation[reports1-blocked]",
        "test_original_ralph_script_executes_without_native_translation[reports2-complete]",
        "test_original_ralph_script_executes_without_native_translation[reports3-budget-limited]",
        "test_script_parse_fails_before_publication[export const meta = {};return 1]",
        "test_script_parse_fails_before_publication[return {]",
        "test_workflow_tool_executes_caller_functions_and_records_real_children",
    },
    'test_http_redirect_source': {
        *{'test_actual_source_redirect_method_body_headers_limit_and_abort_match[' + name + ']' for name in REDIRECT_NAMES},
        *{'test_redirect_receipt_refuses_incomplete_or_foreign_runtime[' + damage + ']' for damage in (
            'missing-module', 'changed-module', 'empty-closure', 'foreign-root', 'foreign-python', 'missing-row', 'duplicate-row', 'changed-row')},
    },
    'test_current_release_gate': {
        'test_process_artifact_retention_lanes_are_mandatory[omit]',
        'test_process_artifact_retention_lanes_are_mandatory[skip]',
        'test_process_artifact_retention_lanes_are_mandatory[duplicate]',
        'test_process_artifact_retention_lanes_are_mandatory[failure]',
        *{'test_extracted_llm_prepared_requires_complete_values_and_runtime[' + damage + ']' for damage in ('missing', 'source-missing', 'source-changed', 'module-changed', 'config', 'boolean', 'defaults', 'context', 'error', 'dispatch', 'trace', 'replay', 'signal', 'frozen', 'header', 'empty', 'message-form', 'message-split', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module')},
        *{'test_llm_prepared_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit','skip','duplicate','failure')},
        *{'test_extracted_llm_metadata_requires_complete_values_and_runtime[' + damage + ']' for damage in ('missing', 'source-missing', 'source-changed', 'module-changed', 'model', 'context', 'reasoning', 'description', 'max-tokens', 'modalities', 'trace', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module')},
        *{'test_llm_metadata_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_extracted_canonical_llm_requires_complete_values_and_runtime[' + damage + ']' for damage in ('missing', 'source-missing', 'source-changed', 'module-changed', 'request', 'event', 'tool-id', 'message-form', 'message-split', 'message-cross-fixture', 'retry-form', 'retry-split', 'retry-cross-fixture', 'tail', 'duplicate', 'order', 'type', 'root', 'python', 'executable', 'module', 'group-missing', 'group-rows', 'group-root', 'group-executable', 'group-module')},
        *{'test_canonical_llm_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit','skip','duplicate','failure')},
        *{'test_extracted_jsonl_sharing_requires_complete_values_and_runtime[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'root', 'python', 'executable',
            'header', 'event', 'raw', 'filename', 'tail', 'duplicate', 'order')},
        *{'test_jsonl_sharing_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_extracted_read_requires_source_assets_and_complete_observations[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'assets-missing',
            'asset-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'outcome', 'late-return', 'signal', 'queue', 'legacy')},
        *{'test_read_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_extracted_initial_requires_source_assets_and_complete_observations[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'assets-missing',
            'asset-changed', 'root', 'python', 'executable', 'tail', 'duplicate', 'outcome', 'late-phase', 'entry', 'emission')},
        *{'test_extracted_number_requires_source_and_complete_metadata[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'root',
            'python', 'executable', 'tail', 'duplicate', 'outcome', 'metadata', 'mutation', 'input',
            'clone-missing', 'clone-deep', 'clone-shallow', 'clone-original')},
        *{'test_number_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_extracted_diagnostic_requires_exact_errors_and_source[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'root',
            'python', 'executable', 'tail', 'duplicate', 'accepted', 'error-name', 'error-text', 'lossless-first', 'restore-negative-zero')},
        *{'test_diagnostic_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_extracted_restore_sign_requires_numeric_identity_and_source[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'root',
            'python', 'executable', 'tail', 'duplicate', 'accepted', 'signed-zero', 'input-value', 'safe-integer', 'error-text')},
        *{'test_restore_sign_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_extracted_full_request_requires_complete_graph_and_source[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'root',
            'python', 'executable', 'tail', 'duplicate', 'provider', 'assistant-alias', 'token-alias',
            'reasoning-alias', 'message-owner', 'signal-owner', 'signal-state')},
        *{'test_full_request_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_extracted_deepseek_error_requires_complete_rows_and_source[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed',
            'root', 'python', 'executable', 'tail', 'duplicate', 'error-name', 'error-message',
            'failure-message', 'preview', 'surrogate', 'timer', 'fraction', 'chunk', 'request-body')},
        *{'test_deepseek_error_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_extracted_deepseek_capture_requires_complete_rows_and_source[' + damage + ']' for damage in ('missing', 'source-missing', 'source-changed', 'module-missing', 'module-changed', 'config-name', 'config-message', 'error-name', 'error-message', 'failure-message', 'error-code', 'file-message', 'file-failure', 'file-quota', 'file-status', 'settings-model', 'settings-provider', 'settings-retry', 'stream', 'serialization', 'usage', 'request-body', 'accepted', 'origin', 'retry-failure', 'retry-delay', 'retry-policy', 'retry-number', 'retry-split', 'retry-shared', 'retry-form', 'tail', 'duplicate', 'root', 'python', 'executable')},
        *{'test_deepseek_capture_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        *{'test_initial_consumer_lanes_are_mandatory[' + damage + ']' for damage in ('omit', 'skip', 'duplicate', 'failure')},
        "test_extracted_ready_requires_source_assets_and_complete_observations[missing]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[source-missing]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[source-changed]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[module-missing]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[module-changed]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[assets-missing]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[asset-changed]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[root]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[python]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[executable]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[tail]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[duplicate]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[outcome]",
        "test_extracted_ready_requires_source_assets_and_complete_observations[late-phase]",
        "test_ready_consumer_lanes_are_mandatory[omit]",
        "test_ready_consumer_lanes_are_mandatory[skip]",
        "test_ready_consumer_lanes_are_mandatory[duplicate]",
        "test_ready_consumer_lanes_are_mandatory[failure]",
        "test_extracted_context_requires_source_identity_and_complete_messages[missing]",
        "test_extracted_context_requires_source_identity_and_complete_messages[source-missing]",
        "test_extracted_context_requires_source_identity_and_complete_messages[source-changed]",
        "test_extracted_context_requires_source_identity_and_complete_messages[module-missing]",
        "test_extracted_context_requires_source_identity_and_complete_messages[module-changed]",
        "test_extracted_context_requires_source_identity_and_complete_messages[root]",
        "test_extracted_context_requires_source_identity_and_complete_messages[python]",
        "test_extracted_context_requires_source_identity_and_complete_messages[executable]",
        "test_extracted_context_requires_source_identity_and_complete_messages[tail]",
        "test_extracted_context_requires_source_identity_and_complete_messages[duplicate]",
        "test_extracted_context_requires_source_identity_and_complete_messages[attribution]",
        "test_extracted_context_requires_source_identity_and_complete_messages[identity-correlation]",
        "test_runtime_context_consumer_lanes_are_mandatory[omit]",
        "test_runtime_context_consumer_lanes_are_mandatory[skip]",
        "test_runtime_context_consumer_lanes_are_mandatory[duplicate]",
        "test_runtime_context_consumer_lanes_are_mandatory[failure]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[missing]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[source-missing]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[source-changed]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[module-missing]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[module-changed]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[assets-missing]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[asset-changed]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[root]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[python]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[executable]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[tail]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[duplicate]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[changed]",
        "test_extracted_javascript_requires_fresh_source_modules_assets_and_whole_observations[late-log]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[omit-test_javascript_runtime]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[omit-test_javascript_workflow_session]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[omit-test_javascript_workflow_host]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[omit-test_javascript_workflow_consumers]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[skip-test_javascript_runtime]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[skip-test_javascript_workflow_session]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[skip-test_javascript_workflow_host]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[skip-test_javascript_workflow_consumers]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[duplicate-test_javascript_runtime]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[duplicate-test_javascript_workflow_session]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[duplicate-test_javascript_workflow_host]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[duplicate-test_javascript_workflow_consumers]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[failure-test_javascript_runtime]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[failure-test_javascript_workflow_session]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[failure-test_javascript_workflow_host]",
        "test_javascript_runtime_and_source_consumer_lanes_are_mandatory[failure-test_javascript_workflow_consumers]",
        *{'test_extracted_redirect_requires_fresh_source_and_owned_runtime[' + damage + ']' for damage in (
            'missing', 'source-missing', 'source-changed', 'modules-missing', 'module-changed', 'foreign-root', 'missing-observation')},
    },
    'test_agent_loop_parallel_settings': {
        *{'test_direct_parallel_cap_rejects_invalid_numbers[' + value + ']' for value in ('0', '-1', '1.5', 'True', '2', 'nan', 'inf')},
        *{'test_direct_parallel_cap_resolves_original_default_and_integer_numbers[config' + str(index) + '-' + str(value) + ']'
          for index, value in enumerate((10, 1, 2))},
        'test_parallel_settings_layers_refuses_and_unloads_reversibly',
        *{'test_factory_model_turn_honors_configured_parallel_pool[' + str(value) + ']' for value in (1, 2, 10)},
    },
    'test_tool_scheduler_source': {
        *{'test_actual_source_dispatch_prefix_precedes_later_preparation_and_drains_owned_work[' + implementation + '-' + action + ']'
          for implementation in ('custom-future', 'canonical-body') for action in ('none', 'abort', 'reclassify', 'throw')},
        'test_actual_source_parallel_caps_settings_and_factory_consumers_match',
        'test_actual_source_in_flight_group_keeps_cap_until_exclusive_barrier',
        'test_scheduler_source_order_is_part_of_identity',
        *{'test_scheduler_receipt_refuses_incomplete_or_foreign_observations[' + damage + ']' for damage in (
            'missing-module', 'changed-module', 'empty-closure', 'foreign-root', 'foreign-python', 'missing-row', 'duplicate-row', 'changed-row')},
    },
    'test_upstream_delta': {
        'test_real_readonly_delta_preserves_checkout_and_maps_both_rename_owners_and_consumers',
        'test_nul_parser_preserves_whitespace_unicode_and_both_copy_names',
        *{'test_invalid_git_stream_is_refused[' + name + ']' for name in (
            'M\\x00name', 'R100\\x00old\\x00', 'A\\x00\\x00', 'R101\\x00old\\x00new\\x00',
            'Q\\x00name\\x00', 'M\\x00../outside\\x00', 'M\\x00/absolute\\x00')},
        *{'test_readonly_observer_refuses_changed_or_incomplete_inventory[' + damage + ']'
          for damage in ('dirty', 'wrong-pin', 'hash', 'dependency', 'name', 'missing', 'duplicate')},
        'test_invalid_revision_cannot_become_a_git_option_or_write',
        'test_source_drift_during_observation_is_refused',
        'test_report_output_is_exclusive_and_cannot_change_source_git_or_migration',
        'test_actual_pinned_source_parent_delta_is_readonly_and_source_qualified',
    },
    'test_tool_scheduler_failure_boundaries': {
        'test_ordered_scheduler_finishes_actual_prepared_and_dispatched_results[pre-error-expected0]',
        'test_ordered_scheduler_finishes_actual_prepared_and_dispatched_results[around-error-expected1]',
        'test_ordered_scheduler_finishes_actual_prepared_and_dispatched_results[pre-deny-expected2]',
        'test_ordered_scheduler_finishes_actual_prepared_and_dispatched_results[success-expected3]',
        'test_scheduler_preserves_first_failure_and_drains_without_late_dispatch[False]',
        'test_scheduler_preserves_first_failure_and_drains_without_late_dispatch[True]',
    },
    'test_deepseek_image_journey': {
        'test_extension_request_idle_watchdog_tracks_partial_wire_activity',
        'test_extension_idle_watchdog_does_not_charge_settled_reader_delivery',
    },
    'test_profile_spine_recovery': {'test_profile_tool_turn_persists_and_resumes_after_shutdown'},
    'test_jsonl_canonical': {
        'test_canonical_registry_uses_lazy_default_checksummed_zstd',
        'test_torn_tail_inspection_is_inert_and_load_commits_repair[zstd]',
        'test_torn_tail_inspection_is_inert_and_load_commits_repair[none]',
        'test_encoding_refusal_preserves_original_artifact',
        'test_jsonl_paths_encode_original_utf16_units',
        'test_cancelled_read_drains_actual_worker_before_return',
        'test_revision_change_retries_actual_file_read',
        'test_append_sync_failure_restores_prefix_or_retains_both_causes[False]',
        'test_append_sync_failure_restores_prefix_or_retains_both_causes[True]',
    },
    'test_jsonl_provider_source': {'test_actual_source_and_native_compressed_jsonl_mutual_files_and_cold_consumers'},
    'test_jsonl_metadata_boundaries': {
        *{'test_present_null_survives_physical_reads_and_is_refused_at_its_owned_boundary[' + field + '-' + compression + ']'
          for field in ('cwd', 'parentSession', 'seedLength') for compression in ('zstd', 'none')},
        *{'test_nonstring_cwd_preserves_original_project_identity_refusal[' + value + '-' + compression + ']'
          for value in ('False', '1', 'cwd2') for compression in ('zstd', 'none')},
        *{'test_unsupported_format_retains_public_name_and_actual_raw_location[' + version + '-' + compression + ']'
          for version in ('-1', '1', '0.5', '1e999') for compression in ('zstd', 'none')},
    },
    'test_sqlite_canonical': {
        'test_canonical_registry_and_unchanged_closed_sql_resources',
        'test_actual_lazy_store_packed_seek_and_detached_revision',
        'test_canonical_plugin_cold_torn_repair_and_unpublished_end_seed',
        'test_existing_page_size_and_revision_survive_reopen',
        'test_current_mutation_ownership_rechecked_before_writing',
        'test_cancelled_waiter_does_not_cancel_shared_open',
        'test_empty_mutations_and_missing_materialization_are_inert',
        'test_busy_journal_retry_reuses_real_handle_and_keeps_security',
        'test_failed_transaction_and_rollback_keep_both_causes',
        *{'test_failed_journal_attempt_preserves_budget_and_retires_real_handle[' + name + ']' for name in (
            'zero-budget', 'non-busy', 'cutoff')},
        *{'test_foreign_layout_refusal_preserves_actual_file_and_closes_handle[' + name + ']' for name in (
            'unversioned', 'old', 'future', 'foreign', 'altered')},
    },
    'test_sqlite_provider_source': {'test_actual_source_and_native_schema19_mutual_files_and_consumers'},
    'test_sqlite_remote': {
        'test_canonical_sqlite_remote_model_fork_search_and_cold_restart[minimal]',
        'test_canonical_sqlite_remote_model_fork_search_and_cold_restart[standard]',
        'test_canonical_sqlite_remote_model_fork_search_and_cold_restart[cordis]',
    },
    'test_sqlite_format': {
        'test_schema_owned_packed_rows_survive_actual_strict_sqlite_and_detached_reads',
        'test_physical_corruption_is_repairable_only_without_a_later_valid_turn_end[False]',
        'test_physical_corruption_is_repairable_only_without_a_later_valid_turn_end[True]',
        'test_packed_output_is_bounded_during_decompression_before_json_parse',
        'test_fatal_utf8_and_bom_match_original_data_column_semantics',
        'test_surface_fields_validate_before_malformed_scalar_data',
        'test_scalar_json_numbers_use_ieee754_and_refuse_non_json_constants',
        'test_provenance_run_expansion_is_bounded_before_allocation',
        'test_zstd_builder_exposes_explicit_staging_inputs',
        'test_hash_pinned_zstd_assets_preserve_exact_git_checkout_bytes',
        *{'test_changed_private_zstd_assets_fail_closed[' + name + ']' for name in (
            'dsh_zstd.dll', 'zstd-dictionary.bin', 'zstd.json', 'build-provenance.json', 'ZSTD-LICENSE', 'LLVM-LICENSE.txt', 'MinGW-COPYING')},
        *{'test_private_decoder_preserves_complete_output_across_buffer_boundaries[' + str(size) + ']' for size in (
            65535, 65536, 65537, 100000, 131072, 200000, 1048576)},
    },
    'test_sqlite_format_source': {'test_actual_schema19_format_source_native_pair'},
    'test_session_tools': {
        'test_optional_plugin_registers_and_reverses_all_five_tools_and_prompt',
        'test_caller_abort_wins_over_late_provider_result_and_drains[False]',
        'test_caller_abort_wins_over_late_provider_result_and_drains[True]',
        'test_preabort_never_invokes_or_logs_provider',
        'test_hostile_error_code_and_logging_fail_closed',
        'test_title_observation_reauthorizes_exact_header_before_exposing_content[caller]',
        'test_title_observation_reauthorizes_exact_header_before_exposing_content[other]',
        'test_deep_lineage_prunes_foreign_subtrees_without_recursion_or_hidden_ids',
        'test_search_deadline_reaches_authorization_and_waits_for_owned_cleanup',
    },
    'test_session_tools_source': {'test_actual_optional_session_tools_source_native_pair'},
    'test_session_tools_profile': {
        'test_optional_profile_model_tools_next_request_and_cold_restart[jsonl]',
        'test_optional_profile_model_tools_next_request_and_cold_restart[jsonl-zstd]',
        'test_optional_profile_model_tools_next_request_and_cold_restart[sqlite]',
    },
    "test_session_text": {
        "test_literal_simple_case_equivalents_match_in_both_directions[\\u0412-\\u1c80]",
        "test_literal_simple_case_equivalents_match_in_both_directions[\\ua7cb-\\u0264]",
        "test_literal_simple_case_equivalents_match_in_both_directions[\\U00010d50-\\U00010d70]",
        "test_literal_simple_case_equivalents_match_in_both_directions[\\u1e9e-\\xdf]",
        "test_literal_simple_case_equivalents_match_in_both_directions[s-\\u017f]",
        "test_literal_simple_case_equivalents_match_in_both_directions[k-\\u212a]",
        "test_literal_simple_case_equivalents_match_in_both_directions[\\u0392-\\u03d0]",
        "test_literal_matching_refuses_full_fold_turkic_and_normalization[\\xdf-ss]",
        "test_literal_matching_refuses_full_fold_turkic_and_normalization[\\u0130-i]",
        "test_literal_matching_refuses_full_fold_turkic_and_normalization[\\u0131-I]",
        "test_literal_matching_refuses_full_fold_turkic_and_normalization[\\xe9-e\\u0301]",
        "test_literal_matching_refuses_full_fold_turkic_and_normalization[a-b]",
        "test_literal_unicode_mode_preserves_utf16_scalar_boundaries[\\ud83d\\ude00-\\U0001f600-True]",
        "test_literal_unicode_mode_preserves_utf16_scalar_boundaries[\\U0001f600-\\ud83d\\ude00-True]",
        "test_literal_unicode_mode_preserves_utf16_scalar_boundaries[\\ud83d-\\U0001f600-False]",
        "test_literal_unicode_mode_preserves_utf16_scalar_boundaries[\\ud83d-\\ud83d\\ude00-False]",
        "test_literal_unicode_mode_preserves_utf16_scalar_boundaries[\\ude00-\\U0001f600-False]",
        "test_literal_unicode_mode_preserves_utf16_scalar_boundaries[\\ude00-\\ud83d\\ude00-False]",
        "test_literal_unicode_mode_preserves_utf16_scalar_boundaries[\\ud83d-\\ud83d-True]",
        "test_literal_unicode_mode_preserves_utf16_scalar_boundaries[\\ude00-\\ude00-True]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\t]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\n]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\r]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[ ]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\xa0]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\u1680]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\u2000]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\u200a]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\u2028]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\u2029]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\u202f]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\u205f]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\u3000]",
        "test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty[\\ufeff]",
        "test_other_python_whitespace_remains_literal_and_semantic[\\x1c]",
        "test_other_python_whitespace_remains_literal_and_semantic[\\x1d]",
        "test_other_python_whitespace_remains_literal_and_semantic[\\x1e]",
        "test_other_python_whitespace_remains_literal_and_semantic[\\x1f]",
        "test_other_python_whitespace_remains_literal_and_semantic[\\x85]",
        "test_other_python_whitespace_remains_literal_and_semantic[\\u180e]",
        "test_other_python_whitespace_remains_literal_and_semantic[\\u200b]",
        "test_other_python_whitespace_remains_literal_and_semantic[\\u2060]",
        "test_literal_regex_operators_and_nul_are_data",
        "test_missing_or_changed_case_folding_data_is_refused[missing]",
        "test_missing_or_changed_case_folding_data_is_refused[changed]",
        "test_corpus_and_lineage_preserve_equal_collation_insertion_order[identities0]",
        "test_corpus_and_lineage_preserve_equal_collation_insertion_order[identities1]",
        "test_canonical_durable_text_filters_repeat_after_context_restart[jsonl]",
        "test_canonical_durable_text_filters_repeat_after_context_restart[sqlite]",
    },
    "test_session_text_source": {
        "test_actual_original_native_text_extraction_and_domain_order",
    },
    "test_query_unicode": {
        "test_canonical_and_ignorable_strings_preserve_stable_order[\\xe9-e\\u0301]",
        "test_canonical_and_ignorable_strings_preserve_stable_order[ab-a\\u200bb]",
        "test_canonical_and_ignorable_strings_preserve_stable_order[ab-a\\xadb]",
        "test_canonical_and_ignorable_strings_preserve_stable_order[ab-a\\u2060b]",
        "test_canonical_and_ignorable_strings_preserve_stable_order[a\\u0315\\u0300-\\xe0\\u0315]",
        "test_nullable_fingerprint_preserves_source_case_order",
        "test_equivalent_strings_retain_distinct_request_fingerprints",
        "test_utf16_embedded_nul_and_unpaired_surrogates_are_not_truncated",
        "test_collator_close_is_idempotent_and_refuses_late_comparisons",
        "test_runtime_identity_copies_metadata_and_reports_loaded_files",
        "test_changed_manifest_refused_before_loading[version-value0]",
        "test_changed_manifest_refused_before_loading[version-value1]",
        "test_changed_manifest_refused_before_loading[unicode_version-value2]",
        "test_changed_manifest_refused_before_loading[cldr_version-value3]",
        "test_changed_manifest_refused_before_loading[dll_sha256-value4]",
        "test_changed_manifest_refused_before_loading[license_sha256-value5]",
        "test_missing_runtime_or_license_refused_before_loading[dsh_icudt78.dll]",
        "test_missing_runtime_or_license_refused_before_loading[dsh_icuuc78.dll]",
        "test_missing_runtime_or_license_refused_before_loading[dsh_icuin78.dll]",
        "test_missing_runtime_or_license_refused_before_loading[ICU-LICENSE]",
        "test_missing_runtime_or_license_refused_before_loading[LLVM-LICENSE.txt]",
        "test_corrupt_private_library_refused_before_loading",
        "test_legacy_windows_loader_flags_are_used_for_all_libraries",
        "test_portable_input_verification_does_not_load_libraries",
    },
    "test_query_unicode_source": {
        "test_actual_original_native_unicode_and_cursor_observations",
    },
    "test_session_remote": {
        "test_session_remote_create_follow_rename_resume[minimal]",
        "test_session_remote_create_follow_rename_resume[standard]",
        "test_session_remote_create_follow_rename_resume[cordis]",
    },
    "test_query_engine": {
        "test_query_engine_abort_ignoring_source_holds_serialization_until_cleanup[inspect]",
        "test_query_engine_abort_ignoring_source_holds_serialization_until_cleanup[list]",
        "test_query_engine_actual_cordis_publication_readiness_and_retirement[first-search]",
        "test_query_engine_actual_cordis_publication_readiness_and_retirement[never]",
        "test_query_engine_actual_cordis_publication_readiness_and_retirement[startup]",
        "test_query_engine_actual_durable_search_incremental_revision_and_live_preference[jsonl]",
        "test_query_engine_actual_durable_search_incremental_revision_and_live_preference[sqlite]",
        "test_query_engine_actual_live_events_page_rank_owned_request_and_filter_budgets",
        "test_query_engine_close_drains_accepted_source_and_refuses_queued_work",
        "test_query_engine_configuration_refuses_before_context_access[patch0-path must not be blank]",
        "test_query_engine_configuration_refuses_before_context_access[patch1-path must not be blank]",
        "test_query_engine_configuration_refuses_before_context_access[patch2-openAt is not supported]",
        "test_query_engine_configuration_refuses_before_context_access[patch3-defaultLimit must be an integer between 1 and 9007199254740990]",
        "test_query_engine_configuration_refuses_before_context_access[patch4-maxLimit must be an integer between 1 and 9007199254740990]",
        "test_query_engine_configuration_refuses_before_context_access[patch5-snippetChars must be a positive integer]",
        "test_query_engine_configuration_refuses_before_context_access[patch6-readWindowMax must be a non-negative integer]",
        "test_query_engine_configuration_refuses_before_context_access[patch7-persistedInspectConcurrency must be a positive safe integer]",
        "test_query_engine_configuration_refuses_before_context_access[patch8-defaultLimit must be less than or equal to maxLimit]",
        "test_query_engine_configuration_refuses_before_context_access[patch9-journalMode is not supported]",
        "test_query_engine_cursor_rejects_foreign_or_unsafe_offset[-1]",
        "test_query_engine_cursor_rejects_foreign_or_unsafe_offset[1.5]",
        "test_query_engine_cursor_rejects_foreign_or_unsafe_offset[9007199254740992]",
        "test_query_engine_cursor_rejects_foreign_or_unsafe_offset[None]",
        "test_query_engine_cursor_rejects_foreign_or_unsafe_offset[True]",
        "test_query_engine_failed_readiness_is_shared_and_closed_once",
        "test_query_engine_failed_transaction_preserves_both_fts_generations_and_next_search",
        "test_query_engine_optional_provider_child_disposal_waits_for_cleanup",
        "test_query_engine_preabort_disabled_and_invalid_requests_never_open",
        "test_query_engine_readiness_non_error_value_preserves_source_wait_boundary[False]",
        "test_query_engine_readiness_non_error_value_preserves_source_wait_boundary[True]",
        "test_query_engine_shared_readiness_abort_and_close_drain",
    },
    "test_query_engine_source": {
        "test_actual_original_native_query_engine_boundaries",
    },
    "test_sqlite_database": {
        "test_pinned_database_coexists_with_loaded_stdlib_and_enforces_strict_types",
        "test_pinned_database_preserves_bound_storage_values[None]",
        "test_pinned_database_preserves_bound_storage_values[-9223372036854775808]",
        "test_pinned_database_preserves_bound_storage_values[9223372036854775807]",
        "test_pinned_database_preserves_bound_storage_values[1.25]",
        "test_pinned_database_preserves_bound_storage_values[\\u4e2d\\u6587\\x00\\U0001f600]",
        "test_pinned_database_preserves_bound_storage_values[\\x00\\xff]",
        "test_pinned_database_preserves_bound_storage_values[0]",
        "test_pinned_database_preserves_bound_storage_values[1]",
        "test_pinned_database_preserves_bound_storage_values[value8]",
        "test_pinned_database_preserves_bound_storage_values[value9]",
        "test_pinned_database_fts5_unicode61_rank_and_highlight",
        "test_pinned_database_failed_statement_finalizes_and_transaction_rolls_back",
        "test_pinned_database_refuses_unsupported_bindings_without_retaining_statement[True]",
        "test_pinned_database_refuses_unsupported_bindings_without_retaining_statement[9223372036854775808]",
        "test_pinned_database_refuses_unsupported_bindings_without_retaining_statement[value2]",
        "test_pinned_database_refuses_unsupported_bindings_without_retaining_statement[value3]",
        "test_pinned_database_refuses_multi_statement_and_nul_sql_then_retires",
    },
    "test_query_schema": {
        "test_actual_query_schema_keeps_live_tables_local_to_each_connection",
        "test_actual_query_schema_rolls_back_main_and_temporary_fts_as_one_transaction",
        "test_failed_query_schema_initialization_closes_unpublished_real_connection",
        "test_query_schema_refuses_journal_modes_before_file_creation[off]",
        "test_query_schema_refuses_journal_modes_before_file_creation[memory]",
        "test_query_schema_refuses_journal_modes_before_file_creation[wal;DROP TABLE search_state]",
    },
    "test_session_windows_dll_loading": {
        "test_session_dll_loading_uses_unpatched_windows_loader_flags[attributes]",
        "test_session_dll_loading_uses_unpatched_windows_loader_flags[query]",
    },
    "test_query_schema_source": {
        "test_source_query_schema_contract",
    },
    'test_python_directory_mutation': {
        'test_actual_package_publication_waits_for_released_sharing_owner[' + operation + '-' + location + ']'
        for operation in ('add', 'upgrade', 'rollback') for location in ('directory', 'file')
    } | {'test_permanent_directory_holder_preserves_complete_pending_transaction[' + location + ']'
         for location in ('directory', 'file')}
      | {'test_nonsharing_directory_publication_error_is_immediate_and_exact',
         'test_directory_publication_collision_preserves_both_owned_and_foreign_data'},
    'test_gateway_mux_write_lifetime': {
        'test_closed_mux_refuses_item_before_mutating_codec_or_writing[' + value + ']'
        for value in ('False', 'True')
    } | {'test_queued_mux_write_rechecks_physical_close_after_prior_delivery',
         'test_late_stream_item_after_socket_close_drains_without_terminal_or_error_frame',
         'test_terminate_on_closed_transport_finishes_without_close_frame'},
    'test_session_snapshots_source': {'test_source_session_snapshots_contract'},
    'test_session_snapshots': {
        name + '[' + backend + ']' for name in (
            'test_actual_durable_snapshot_revisions_track_owned_batches_and_reopen',
            'test_actual_durable_snapshot_preabort_has_exact_reason_without_listing')
        for backend in ('jsonl', 'sqlite')
    } | {
        'test_jsonl_snapshot_stat_failure_and_abort_priority[' + pair + ']'
        for pair in ('False-False', 'True-False', 'False-True', 'True-True')
    } | {'test_sqlite_revision_upgrade_preserves_existing_header_and_incarnation',
         'test_failed_sqlite_revision_upgrade_rolls_back_ddl_and_backfill',
         'test_failed_sqlite_event_batch_rolls_back_revision_with_event_suffix',
         'test_windows_file_revision_handles_are_closed_after_success_and_stat_failure',
         'test_two_sqlite_instances_observe_same_namespace_and_atomic_revision',
         'test_windows_file_revision_supports_long_unicode_paths_without_os_patches'},
    'test_webserver_peer_reset': {
        'test_owned_socket_contains_only_windows_peer_reset_at_shutdown[' + value + ']'
        for value in ('10054', '10053', 'None')
    } | {'test_reset_during_actual_proactor_cleanup_closes_socket_and_notifies_once',
         'test_owned_listener_cancellation_releases_accept_and_bound_port'} | {
        'test_real_peer_resets_retire_owned_connections_and_leave_host_healthy[' + value + ']'
        for value in ('False', 'True')},
    'test_session_requests_source': {'test_source_session_requests_contract'},
    'test_session_sqlite_query_source': {'test_unchanged_original_sqlite_query_specs'},
    'test_session_requests': {
        name + '[' + backend + ']' for name in (
            'test_actual_durable_search_request_captures_query_before_await',
            'test_actual_durable_invalid_search_precedes_abort_and_index_access')
        for backend in ('jsonl', 'sqlite')},
    'test_session_filters_source': {'test_source_session_filters_contract'},
    'test_session_filters': {
        name + '[' + backend + ']' for name in (
            'test_actual_durable_filters_hold_inputs_before_await_and_classify_surface',
            'test_actual_durable_filter_pre_abort_and_invalid_bounds_do_not_access_backend')
        for backend in ('jsonl', 'sqlite')},
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
        'test_browser_extension_isolation_preserves_application_error_observation',
        'test_original_browser_native_host_cordis_lifecycle[lifecycle]',
        'test_original_browser_native_host_cordis_lifecycle[inspect]',
        'test_original_browser_native_host_cordis_lifecycle[inventory-layout-boundary]',
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
        process = subprocess.Popen(command, cwd=str(cwd or ROOT), stdout=stream,
                                   stderr=subprocess.STDOUT, env=env, start_new_session=os.name != 'nt')
        try:
            return_code = process.wait(timeout=timeout)
        except BaseException as failure:
            cleanup = dict(root_pid=process.pid, primary_failure=type(failure).__name__)
            try:
                if process.poll() is None:
                    if os.name == 'nt':
                        stopped = subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
                        cleanup.update(tree_exit_code=stopped.returncode, tree_output_hex=stopped.stdout.hex())
                        if stopped.returncode != 0 and process.poll() is None:
                            raise RuntimeError('Owned release process tree did not stop')
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
            except Exception as cleanup_failure:
                cleanup['cleanup_failure'] = dict(name=type(cleanup_failure).__name__, message=str(cleanup_failure))
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                cleanup['root_exit_code'] = process.returncode
                try:
                    (output / (name + '-cleanup.json')).write_text(json.dumps(cleanup, indent=2) + '\n', encoding='utf-8')
                except OSError as audit_failure:
                    failure.cleanup_audit_failure = str(audit_failure)
            raise
    if return_code not in accepted:
        raise RuntimeError('%s failed (%d); see %s' % (name, return_code, output / (name + '.log')))
    return return_code


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
    try:
        if not isinstance(candidate['query_unicode_observations_sha256'], str) or not isinstance(candidate['query_unicode_locale'], str):
            raise ValueError('Unicode source identity is missing')
        validate_query_unicode(report.get('queryUnicode'), report['mcpStdio']['root'],
                               candidate['query_unicode_observations_sha256'], candidate['query_unicode_locale'])
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted queryUnicode observations are incomplete') from error
    try:
        if not isinstance(candidate['session_text_observations_sha256'], str) or not isinstance(candidate['session_text_locale'], str):
            raise ValueError('Session text source identity is missing')
        validate_session_text(report.get('sessionText'), report['mcpStdio']['root'],
                              candidate['session_text_observations_sha256'], candidate['session_text_locale'])
        input_digest = candidate['session_text_inputs_sha256']
        if not isinstance(input_digest, str) or not re.fullmatch(r'[0-9a-f]{64}', input_digest) or report.get('sessionTextInputSha256') != input_digest:
            raise ValueError('Session text input receipt differs')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted sessionText observations are incomplete') from error
    try:
        if not isinstance(candidate['session_tools_observations_sha256'], str) or not isinstance(candidate['session_tools_modules'], dict):
            raise ValueError('Session tool source digest is missing')
        validate_session_tools(report.get('sessionTools'), report['mcpStdio']['root'],
                               candidate['session_tools_observations_sha256'], candidate['session_tools_modules'])
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted sessionTools observations are incomplete') from error
    try:
        required = ('sqlite_format_observations_sha256', 'sqlite_format_frames_sha256', 'sqlite_format_inputs_sha256')
        if any(not isinstance(candidate[name], str) or not re.fullmatch('[0-9a-f]{64}', candidate[name]) for name in required):
            raise ValueError('SQLite format Source identity is missing')
        if not isinstance(candidate['sqlite_format_modules'], dict) or not isinstance(candidate['sqlite_format_assets'], dict):
            raise ValueError('SQLite format file closure is missing')
        validate_sqlite_format(report.get('sqliteFormat'), report['mcpStdio']['root'],
                              candidate['sqlite_format_observations_sha256'], candidate['sqlite_format_frames_sha256'],
                              candidate['sqlite_format_modules'], candidate['sqlite_format_assets'])
        if report.get('sqliteFormatInputSha256') != candidate['sqlite_format_inputs_sha256']:
            raise ValueError('SQLite format generated inputs differ')
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted sqliteFormat observations are incomplete') from error
    try:
        required = ('sqlite_provider_observations_sha256', 'sqlite_provider_inputs_sha256')
        if any(not isinstance(candidate[name], str) or not re.fullmatch('[0-9a-f]{64}', candidate[name]) for name in required):
            raise ValueError('SQLite provider Source identity is missing')
        if not isinstance(candidate['sqlite_provider_modules'], dict) or not isinstance(candidate['sqlite_provider_assets'], dict):
            raise ValueError('SQLite provider file closure is missing')
        validate_sqlite_provider(report.get('sqliteProvider'), report['mcpStdio']['root'],
            candidate['sqlite_provider_observations_sha256'], candidate['sqlite_provider_inputs_sha256'],
            candidate['sqlite_provider_modules'], candidate['sqlite_provider_assets'])
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted sqliteProvider observations are incomplete') from error
    try:
        required = ('jsonl_provider_observations_sha256', 'jsonl_provider_inputs_sha256')
        if any(not isinstance(candidate[name], str) or not re.fullmatch('[0-9a-f]{64}', candidate[name]) for name in required):
            raise ValueError('JSONL provider Source identity is missing')
        if not isinstance(candidate['jsonl_provider_modules'], dict) or not isinstance(candidate['jsonl_provider_assets'], dict):
            raise ValueError('JSONL provider file closure is missing')
        validate_jsonl_provider(report.get('jsonlProvider'), report['mcpStdio']['root'],
            candidate['jsonl_provider_observations_sha256'], candidate['jsonl_provider_inputs_sha256'],
            candidate['jsonl_provider_modules'], candidate['jsonl_provider_assets'])
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted jsonlProvider observations are incomplete') from error
    try:
        validate_tool_scheduler(report.get('toolScheduler'), Path(report['mcpStdio']['root']),
                                candidate['tool_scheduler_observations_sha256'], candidate['tool_scheduler_modules'])
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted toolScheduler observations are incomplete') from error
    try:
        validate_http_redirect(report.get('httpRedirect'), Path(report['mcpStdio']['root']),
                               candidate['http_redirect_observations_sha256'], candidate['http_redirect_modules'])
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted httpRedirect observations are incomplete') from error
    try:
        validate_javascript_workflow(report.get('javascriptWorkflow'), Path(report['mcpStdio']['root']),
            candidate['javascript_workflow_observations_sha256'], candidate['javascript_workflow_modules'],
            candidate['javascript_workflow_assets'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted javascriptWorkflow observations are incomplete') from error
    try:
        validate_runtime_context(report.get('runtimeContext'), Path(report['mcpStdio']['root']),
            candidate['runtime_context_observations_sha256'], candidate['runtime_context_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted runtimeContext observations are incomplete') from error
    try:
        validate_javascript_ready(report.get('javascriptReady'), Path(report['mcpStdio']['root']),
            candidate['javascript_ready_observations_sha256'], candidate['javascript_ready_modules'],
            candidate['javascript_ready_assets'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted javascriptReady observations are incomplete') from error
    try:
        validate_javascript_initial(report.get('javascriptInitial'), Path(report['mcpStdio']['root']),
            candidate['javascript_initial_observations_sha256'], candidate['javascript_initial_modules'],
            candidate['javascript_initial_assets'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted javascriptInitial observations are incomplete') from error
    try:
        validate_persistence_read(report.get('persistenceRead'), Path(report['mcpStdio']['root']),
            candidate['persistence_read_observations_sha256'], candidate['persistence_read_modules'],
            candidate['persistence_read_assets'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted persistenceRead observations are incomplete') from error
    try:
        validate_session_number(report.get('sessionNumber'), Path(report['mcpStdio']['root']),
            candidate['session_number_observations_sha256'], candidate['session_number_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted sessionNumber observations are incomplete') from error
    try:
        validate_session_diagnostic(report.get('sessionDiagnostic'), Path(report['mcpStdio']['root']),
            candidate['session_diagnostic_observations_sha256'], candidate['session_diagnostic_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted sessionDiagnostic observations are incomplete') from error
    try:
        validate_session_restore_sign(report.get('sessionRestoreSign'), Path(report['mcpStdio']['root']),
            candidate['session_restore_sign_observations_sha256'], candidate['session_restore_sign_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted sessionRestoreSign observations are incomplete') from error
    try:
        validate_runtime_full_request(report.get('runtimeFullRequest'), Path(report['mcpStdio']['root']),
            candidate['runtime_full_request_observations_sha256'], candidate['runtime_full_request_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted runtimeFullRequest observations are incomplete') from error
    try:
        validate_deepseek_error(report.get('deepseekError'), Path(report['mcpStdio']['root']),
            candidate['deepseek_error_observations_sha256'], candidate['deepseek_error_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted deepseekError consumer differs') from error
    try:
        validate_deepseek_capture(report.get('deepseekCapture'), Path(report['mcpStdio']['root']),
            candidate['deepseek_capture_observations_sha256'], candidate['deepseek_capture_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted deepseekCapture consumer differs') from error
    try:
        validate_jsonl_sharing(report.get('jsonlSharing'), Path(report['mcpStdio']['root']),
            candidate['jsonl_sharing_observations_sha256'], candidate['jsonl_sharing_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted jsonlSharing consumer differs') from error
    try:
        validate_canonical_llm(report.get('canonicalLlm'), Path(report['mcpStdio']['root']),
            candidate['canonical_llm_observations_sha256'], candidate['canonical_llm_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted canonicalLlm consumer differs') from error
    try:
        validate_llm_metadata(report.get('llmMetadata'), Path(report['mcpStdio']['root']),
            candidate['llm_metadata_observations_sha256'], candidate['llm_metadata_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted llmMetadata consumer differs') from error
    try:
        validate_llm_prepared(report.get('llmPrepared'), Path(report['mcpStdio']['root']),
            candidate['llm_prepared_observations_sha256'], candidate['llm_prepared_modules'], check_files=False)
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted llmPrepared consumer differs') from error
    for name, validate in [('queryEngine', validate_query_engine), ('querySchema', validate_query_schema), ('pythonDirectory', validate_python_directory),
                           ('sessionLineage', validate_session_lineage), ('sessionEventTrace', validate_session_event_trace),
                           ('sessionFilters', validate_session_filters), ('sessionRequests', validate_session_requests),
                           ('sessionSnapshots', validate_session_snapshots)]:
        try:
            validate(report.get(name))
            if report[name]['root'] != report['mcpStdio']['root']:
                raise ValueError('Session tracing came from a different runtime')
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError('Extracted ' + name + ' observations are incomplete') from error
    if report.get('archiveSha256') != digest(archive) or Path(report['archive']).resolve() != archive.resolve():
        raise RuntimeError('Extracted receipt belongs to a different archive')
    try:
        validate_webserver_reset(report.get('webServerReset'), report['mcpStdio']['root'])
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Extracted WebServer reset cleanup is incomplete') from error
    provenance = report.get('provenance', {})
    if provenance.get('product_commit') != candidate['product_commit']:
        raise RuntimeError('Extracted receipt belongs to a different product commit')
    if not candidate['worktree_dirty'] and provenance.get('worktree_dirty') is not False:
        raise RuntimeError('Clean release requires clean archive provenance')
    return report


def regression_retention_path(path):
    absolute = os.path.abspath(path)
    if os.name != 'nt' or absolute.startswith('\\\\?\\'):
        return absolute
    return '\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute


def run_python_regression(python, output, environment):
    retained = (output / 'pytest-workspace').resolve()
    retained.relative_to(output.resolve())
    if retained.exists():
        raise RuntimeError('Fresh retained pytest workspace required')
    parent = (ROOT / '.goose/out').resolve()
    parent.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix='g-', dir=str(parent))).resolve()
    workspace.relative_to(parent)
    (output / 'pytest-workspace-mapping.json').write_text(json.dumps(dict(
        execution_path=str(workspace), retained_path=str(retained),
        scope='Fresh owned short Windows execution path is independent of the output label. Artifacts move to the retained path after pytest, including failure/timeout; raw observations retain execution paths.'), indent=2) + '\n', encoding='utf-8')
    primary_failure = None
    try:
        run([python, '-m', 'pytest', 'tests', '-ra', '--junitxml=' + str(output / 'pytest.xml'),
            '--basetemp=' + str(workspace)], 'pytest', output, env=environment, timeout=2800)
    except BaseException as failure:
        primary_failure = failure
        raise
    finally:
        if workspace.exists():
            try:
                os.rename(regression_retention_path(workspace), regression_retention_path(retained))
            except OSError as retention_failure:
                try:
                    (output / 'pytest-retention-failure.json').write_text(json.dumps(dict(
                        name=type(retention_failure).__name__, message=str(retention_failure)), indent=2) + '\n', encoding='utf-8')
                except OSError:
                    if primary_failure is None:
                        raise
                if primary_failure is None:
                    raise


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
    output_root = ROOT / '.goose/out'
    cleanup = dict(regressions=prune_previous_regressions(output_root), focused=[], expired_manifests=[])
    focus_folder = output_root / 'acp-a4-work'
    if focus_folder.is_dir():
        cleanup['focused'] = prune_finished_focus_runs(output_root, focus_folder)
        cleanup['expired_manifests'] = expire_finished_manifests(output_root, focus_folder)
    (output / 'process-artifacts-pruned.json').write_text(json.dumps(cleanup, indent=2) + '\n', encoding='utf-8')
    before = source_snapshot()
    inputs = output / 'inputs.json'
    inputs.write_text(json.dumps(before, indent=2) + '\n', encoding='utf-8')
    run([python, 'scripts/migration.py', 'check'], 'migration-records', output, env=environment)
    run([python, 'scripts/build_portable.py', '--ripgrep-source',
         'scripts/oracles/official/node_modules/@vscode/ripgrep-win32-x64/bin/rg.exe'],
        'portable-build', output, env=environment)
    regression = output / 'pytest.xml'
    run_python_regression(python, output, environment)
    regression_result = validate_regression(regression)
    for config in OFFICIAL_CONFIGS:
        run(['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs',
             'run', '--config', 'scripts/oracles/vitest.' + config + '.config.mts'],
            'official-' + config, output, env=environment)
    receipts = {}
    upstream_delta = output / 'upstream-delta.json'
    run([python, 'scripts/upstream_delta.py', '--base', actual + '^', '--target', actual,
         '--output', str(upstream_delta)], 'upstream-delta', output, env=environment)
    delta_report = json.loads(upstream_delta.read_text(encoding='utf-8'))
    if (delta_report.get('result') != 'observed' or delta_report.get('source_pin') != actual
            or delta_report.get('target_commit') != actual or delta_report.get('unchanged_checkout') != actual
            or delta_report.get('base_commit') != git('rev-parse', actual + '^', root=ROOT / 'reference')
            or delta_report.get('inventory_sha256') != digest(ROOT / 'migration/modules.json')):
        raise RuntimeError('Read-only upstream delta Source identity differs')
    receipts['upstream-delta'] = digest(upstream_delta)
    for driver in PAIRED_DRIVERS:
        name = driver.replace('_', '-') + '-paired'
        path = output / (name + '.json')
        path.unlink(missing_ok=True)
        run([python, 'scripts/' + driver + '_oracle.py', '--output', str(path)], name, output, env=environment)
        validate_paired(path)
        receipts[name] = digest(path)
    unicode_source = output / 'query-unicode-paired.source.json'
    unicode_digest, unicode_locale = unicode_source_identity(json.loads(unicode_source.read_text(encoding='utf-8')))
    candidate['query_unicode_observations_sha256'] = unicode_digest
    candidate['query_unicode_locale'] = unicode_locale
    text_source = output / 'session-text-paired.source.json'
    text_inputs = output / 'session-text-paired.inputs.json'
    text_digest, text_locale = text_source_identity(json.loads(text_source.read_text(encoding='utf-8')))
    candidate['session_text_observations_sha256'] = text_digest
    candidate['session_text_locale'] = text_locale
    candidate['session_text_inputs_sha256'] = digest(text_inputs)
    tools_source = output / 'session-tools-paired.source.json'
    candidate['session_tools_observations_sha256'] = tools_source_identity(json.loads(tools_source.read_text(encoding='utf-8')))
    candidate['session_tools_modules'] = tools_module_hashes(ROOT)
    format_source = output / 'sqlite-format-paired.source.json'
    format_inputs = output / 'sqlite-format-paired.inputs.json'
    format_digest, frames_digest = format_source_identity(json.loads(format_source.read_text(encoding='utf-8')))
    candidate['sqlite_format_observations_sha256'] = format_digest
    candidate['sqlite_format_frames_sha256'] = frames_digest
    candidate['sqlite_format_inputs_sha256'] = digest(format_inputs)
    candidate['sqlite_format_modules'] = format_module_hashes(ROOT)
    candidate['sqlite_format_assets'] = format_asset_hashes(ROOT)
    provider_source = output / 'sqlite-provider-paired.source.json'
    provider_inputs = output / 'sqlite-provider-paired.inputs.json'
    candidate['sqlite_provider_observations_sha256'] = provider_source_identity(json.loads(provider_source.read_text(encoding='utf-8')))
    candidate['sqlite_provider_inputs_sha256'] = digest(provider_inputs)
    candidate['sqlite_provider_modules'] = provider_hashes(ROOT, PROVIDER_MODULES)
    candidate['sqlite_provider_assets'] = provider_hashes(ROOT, PROVIDER_ASSETS)
    jsonl_source = output / 'jsonl-provider-paired.source.json'
    jsonl_inputs = output / 'jsonl-provider-paired.inputs.json'
    candidate['jsonl_provider_observations_sha256'] = jsonl_source_identity(json.loads(jsonl_source.read_text(encoding='utf-8')))
    candidate['jsonl_provider_inputs_sha256'] = digest(jsonl_inputs)
    candidate['jsonl_provider_modules'] = provider_hashes(ROOT, JSONL_MODULES)
    candidate['jsonl_provider_assets'] = provider_hashes(ROOT, JSONL_ASSETS)
    scheduler_source = output / 'tool-scheduler-paired.source.json'
    scheduler_native = output / 'tool-scheduler-paired.native.json'
    candidate['tool_scheduler_observations_sha256'] = scheduler_identity(json.loads(scheduler_source.read_text(encoding='utf-8')))
    candidate['tool_scheduler_modules'] = json.loads(scheduler_native.read_text(encoding='utf-8'))['modules']
    redirect_source = output / 'http-redirect-paired.source.json'
    redirect_native = output / 'http-redirect-paired.native.json'
    candidate['http_redirect_observations_sha256'] = redirect_identity(json.loads(redirect_source.read_text(encoding='utf-8')))
    candidate['http_redirect_modules'] = json.loads(redirect_native.read_text(encoding='utf-8'))['modules']
    javascript_source = output / 'javascript-workflow-paired.source.json'
    javascript_native = output / 'javascript-workflow-paired.native.json'
    javascript_report = json.loads(javascript_native.read_text(encoding='utf-8'))
    candidate['javascript_workflow_observations_sha256'] = javascript_identity(json.loads(javascript_source.read_text(encoding='utf-8')))
    candidate['javascript_workflow_modules'] = javascript_report['modules']
    candidate['javascript_workflow_assets'] = javascript_report['assets']
    runtime_context_source = output / 'runtime-context-paired.source.json'
    runtime_context_native = output / 'runtime-context-paired.native.json'
    candidate['runtime_context_observations_sha256'] = runtime_context_identity(json.loads(runtime_context_source.read_text(encoding='utf-8')))
    candidate['runtime_context_modules'] = json.loads(runtime_context_native.read_text(encoding='utf-8'))['modules']
    ready_source = output / 'javascript-ready-paired.source.json'
    ready_native = output / 'javascript-ready-paired.native.json'
    ready_report = json.loads(ready_native.read_text(encoding='utf-8'))
    candidate['javascript_ready_observations_sha256'] = ready_identity(json.loads(ready_source.read_text(encoding='utf-8')))
    candidate['javascript_ready_modules'] = ready_report['modules']
    candidate['javascript_ready_assets'] = ready_report['assets']
    initial_source = output / 'javascript-initial-paired.source.json'
    initial_native = output / 'javascript-initial-paired.native.json'
    initial_report = json.loads(initial_native.read_text(encoding='utf-8'))
    candidate['javascript_initial_observations_sha256'] = initial_identity(json.loads(initial_source.read_text(encoding='utf-8')))
    candidate['javascript_initial_modules'] = initial_report['modules']
    candidate['javascript_initial_assets'] = initial_report['assets']
    read_source = output / 'persistence-read-paired.source.json'
    read_native = output / 'persistence-read-paired.native.json'
    read_report = json.loads(read_native.read_text(encoding='utf-8'))
    candidate['persistence_read_observations_sha256'] = read_identity(json.loads(read_source.read_text(encoding='utf-8')))
    candidate['persistence_read_modules'] = read_report['modules']
    candidate['persistence_read_assets'] = read_report['assets']
    number_source = output / 'session-number-paired.source.json'
    number_native = output / 'session-number-paired.native.json'
    number_report = json.loads(number_native.read_text(encoding='utf-8'))
    candidate['session_number_observations_sha256'] = number_identity(json.loads(number_source.read_text(encoding='utf-8')))
    candidate['session_number_modules'] = number_report['modules']
    diagnostic_source = output / 'session-diagnostic-paired.source.json'
    diagnostic_native = output / 'session-diagnostic-paired.native.json'
    diagnostic_report = json.loads(diagnostic_native.read_text(encoding='utf-8'))
    candidate['session_diagnostic_observations_sha256'] = diagnostic_identity(json.loads(diagnostic_source.read_text(encoding='utf-8')))
    candidate['session_diagnostic_modules'] = diagnostic_report['modules']
    restore_sign_source = output / 'session-restore-sign-paired.source.json'
    restore_sign_native = output / 'session-restore-sign-paired.native.json'
    restore_sign_report = json.loads(restore_sign_native.read_text(encoding='utf-8'))
    candidate['session_restore_sign_observations_sha256'] = restore_sign_identity(json.loads(restore_sign_source.read_text(encoding='utf-8')))
    candidate['session_restore_sign_modules'] = restore_sign_report['modules']
    full_request_source = output / 'runtime-full-request-paired.source.json'
    full_request_native = output / 'runtime-full-request-paired.native.json'
    full_request_report = json.loads(full_request_native.read_text(encoding='utf-8'))
    candidate['runtime_full_request_observations_sha256'] = full_request_identity(json.loads(full_request_source.read_text(encoding='utf-8')))
    candidate['runtime_full_request_modules'] = full_request_report['modules']
    deepseek_error_source = output / 'deepseek-error-paired.source.json'
    deepseek_error_native = output / 'deepseek-error-paired.native.json'
    deepseek_error_report = json.loads(deepseek_error_native.read_text(encoding='utf-8'))
    candidate['deepseek_error_observations_sha256'] = deepseek_error_identity(json.loads(deepseek_error_source.read_text(encoding='utf-8')))
    candidate['deepseek_error_modules'] = deepseek_error_report['modules']
    deepseek_capture_source = output / 'deepseek-capture-paired.source.json'
    deepseek_capture_native = output / 'deepseek-capture-paired.native.json'
    deepseek_capture_report = json.loads(deepseek_capture_native.read_text(encoding='utf-8'))
    candidate['deepseek_capture_observations_sha256'] = deepseek_capture_identity(json.loads(deepseek_capture_source.read_text(encoding='utf-8')))
    candidate['deepseek_capture_modules'] = deepseek_capture_report['modules']
    sharing_source = output / 'jsonl-sharing-paired.source.json'
    sharing_native = output / 'jsonl-sharing-paired.native.json'
    sharing_report = json.loads(sharing_native.read_text(encoding='utf-8'))
    candidate['jsonl_sharing_observations_sha256'] = sharing_identity(json.loads(sharing_source.read_text(encoding='utf-8')))
    candidate['jsonl_sharing_modules'] = sharing_report['modules']
    canonical_llm_source = output / 'canonical-llm-paired.source.json'
    canonical_llm_native = output / 'canonical-llm-paired.native.json'
    canonical_llm_report = json.loads(canonical_llm_native.read_text(encoding='utf-8'))
    candidate['canonical_llm_observations_sha256'] = canonical_llm_identity(json.loads(canonical_llm_source.read_text(encoding='utf-8')))
    candidate['canonical_llm_modules'] = canonical_llm_report['modules']
    llm_metadata_source = output / 'llm-metadata-paired.source.json'
    llm_metadata_native = output / 'llm-metadata-paired.native.json'
    llm_metadata_report = json.loads(llm_metadata_native.read_text(encoding='utf-8'))
    candidate['llm_metadata_observations_sha256'] = llm_metadata_identity(json.loads(llm_metadata_source.read_text(encoding='utf-8')))
    candidate['llm_metadata_modules'] = llm_metadata_report['modules']
    llm_prepared_source = output / 'llm-prepared-paired.source.json'
    llm_prepared_native = output / 'llm-prepared-paired.native.json'
    llm_prepared_report = json.loads(llm_prepared_native.read_text(encoding='utf-8'))
    candidate['llm_prepared_observations_sha256'] = llm_prepared_identity(json.loads(llm_prepared_source.read_text(encoding='utf-8')))
    candidate['llm_prepared_modules'] = llm_prepared_report['modules']
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
               '--browser', str(browser), '--output', str(extracted), '--unicode-source', str(unicode_source),
               '--text-source', str(text_source), '--text-inputs', str(text_inputs), '--tools-source', str(tools_source),
               '--format-source', str(format_source), '--format-inputs', str(format_inputs),
               '--scheduler-source', str(scheduler_source), '--scheduler-native', str(scheduler_native),
               '--redirect-source', str(redirect_source), '--redirect-native', str(redirect_native),
               '--javascript-source', str(javascript_source), '--javascript-native', str(javascript_native),
               '--context-source', str(runtime_context_source), '--context-native', str(runtime_context_native),
               '--ready-source', str(ready_source), '--ready-native', str(ready_native),
               '--initial-source', str(initial_source), '--initial-native', str(initial_native),
               '--read-source', str(read_source), '--read-native', str(read_native),
               '--number-source', str(number_source), '--number-native', str(number_native),
               '--diagnostic-source', str(diagnostic_source), '--diagnostic-native', str(diagnostic_native),
               '--restore-sign-source', str(restore_sign_source), '--restore-sign-native', str(restore_sign_native),
               '--full-request-source', str(full_request_source), '--full-request-native', str(full_request_native),
               '--deepseek-error-source', str(deepseek_error_source), '--deepseek-error-native', str(deepseek_error_native),
               '--deepseek-capture-source', str(deepseek_capture_source), '--deepseek-capture-native', str(deepseek_capture_native),
               '--sharing-source', str(sharing_source), '--sharing-native', str(sharing_native),
               '--canonical-llm-source', str(canonical_llm_source), '--canonical-llm-native', str(canonical_llm_native),
               '--llm-metadata-source', str(llm_metadata_source), '--llm-metadata-native', str(llm_metadata_native),
               '--llm-prepared-source', str(llm_prepared_source), '--llm-prepared-native', str(llm_prepared_native)]
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
