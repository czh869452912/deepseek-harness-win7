import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.runtime_context_oracle import SOURCE_COMMIT, source_pin, validate_executable
from scripts.canonical_llm_oracle import SOURCE_INPUTS as CANONICAL_SOURCE_INPUTS

GROUPS = ('catalog', 'stream')
FIXTURE_PATH = 'scripts/oracles/llm-metadata-fixtures.json'
NAMES_BY_GROUP = json.loads((ROOT / FIXTURE_PATH).read_text(encoding='utf-8'))['names']
NAMES = tuple(group + '/' + name for group in GROUPS for name in NAMES_BY_GROUP[group])
GROUP_MODULES = {'catalog': ['dsh/__init__.py',
             'dsh/cordis/__init__.py',
             'dsh/cordis/awaiting.py',
             'dsh/cordis/context.py',
             'dsh/cordis/environment.py',
             'dsh/cordis/errors.py',
             'dsh/cordis/events.py',
             'dsh/cordis/fiber.py',
             'dsh/cordis/hmr.py',
             'dsh/cordis/include.py',
             'dsh/cordis/loader.py',
             'dsh/cordis/logger.py',
             'dsh/cordis/plugin.py',
             'dsh/cordis/profile.py',
             'dsh/cordis/reflect.py',
             'dsh/cordis/registry.py',
             'dsh/cordis/schema.py',
             'dsh/cordis/service.py',
             'dsh/cordis/timer.py',
             'dsh/cordis/utils.py',
             'dsh/llm/error.py',
             'dsh/llm/llm_service.py',
             'dsh/llm/model_info.py',
             'dsh/typert/__init__.py',
             'dsh/typert/protocol.py',
             'dsh/typert/registry.py',
             'dsh/typert/remote.py',
             'dsh/typert/stores.py'],
 'stream': ['dsh/__init__.py',
            'dsh/cordis/__init__.py',
            'dsh/cordis/awaiting.py',
            'dsh/cordis/context.py',
            'dsh/cordis/environment.py',
            'dsh/cordis/errors.py',
            'dsh/cordis/events.py',
            'dsh/cordis/fiber.py',
            'dsh/cordis/hmr.py',
            'dsh/cordis/include.py',
            'dsh/cordis/json_text.py',
            'dsh/cordis/loader.py',
            'dsh/cordis/logger.py',
            'dsh/cordis/plugin.py',
            'dsh/cordis/profile.py',
            'dsh/cordis/reflect.py',
            'dsh/cordis/registry.py',
            'dsh/cordis/schema.py',
            'dsh/cordis/service.py',
            'dsh/cordis/timer.py',
            'dsh/cordis/utils.py',
            'dsh/core/__init__.py',
            'dsh/core/abort.py',
            'dsh/core/agent.py',
            'dsh/core/agent_default_model_invariant.py',
            'dsh/core/agent_factory.py',
            'dsh/core/agent_loop.py',
            'dsh/core/agent_loop_settings.py',
            'dsh/core/cancellation.py',
            'dsh/core/configured_agents.py',
            'dsh/core/consumed_work.py',
            'dsh/core/inbox.py',
            'dsh/core/json_schema.py',
            'dsh/core/model_selection.py',
            'dsh/core/runtime_context.py',
            'dsh/core/scope.py',
            'dsh/core/session/__init__.py',
            'dsh/core/session/chunk_rows.py',
            'dsh/core/session/invariant.py',
            'dsh/core/session/json.py',
            'dsh/core/session/known_event_types.py',
            'dsh/core/session/preparation.py',
            'dsh/core/session/repair.py',
            'dsh/core/session/request_header.py',
            'dsh/core/session/seq_ranges.py',
            'dsh/core/session/session.py',
            'dsh/core/session/surface.py',
            'dsh/core/session/types.py',
            'dsh/core/surface.py',
            'dsh/core/tool_calls.py',
            'dsh/core/tools.py',
            'dsh/diagnostics/__init__.py',
            'dsh/diagnostics/invariants.py',
            'dsh/llm/adapter_failure.py',
            'dsh/llm/call_config.py',
            'dsh/llm/error.py',
            'dsh/llm/image_content.py',
            'dsh/llm/llm_service.py',
            'dsh/llm/message.py',
            'dsh/llm/model_info.py',
            'dsh/llm/stream_bridge.py',
            'dsh/session/__init__.py',
            'dsh/session/checkpoint_policy.py',
            'dsh/session/checkpoint_policy_invariant.py',
            'dsh/session/durable_publish.py',
            'dsh/session/file_io.py',
            'dsh/session/file_revision.py',
            'dsh/session/icu_collation.py',
            'dsh/session/jsonl_format.py',
            'dsh/session/jsonl_store.py',
            'dsh/session/jsonl_zstd.py',
            'dsh/session/persistence.py',
            'dsh/session/persistence_jsonl_canonical.py',
            'dsh/session/persistence_sqlite_canonical.py',
            'dsh/session/preparations.py',
            'dsh/session/projections.py',
            'dsh/session/repair.py',
            'dsh/session/seq_ranges.py',
            'dsh/session/session_log_deepseek.py',
            'dsh/session/session_log_deepseek_invariant.py',
            'dsh/session/session_query.py',
            'dsh/session/sqlite_codec.py',
            'dsh/session/sqlite_compression.py',
            'dsh/session/sqlite_database.py',
            'dsh/session/sqlite_json.py',
            'dsh/session/sqlite_logical.py',
            'dsh/session/sqlite_schema.py',
            'dsh/session/sqlite_source_seqs.py',
            'dsh/session/sqlite_sql.py',
            'dsh/session/sqlite_store.py',
            'dsh/session/stats.py',
            'dsh/session/text.py',
            'dsh/session/title.py',
            'dsh/session/zstd.py',
            'dsh/settings/__init__.py',
            'dsh/settings/provider.py',
            'dsh/settings/redact.py',
            'dsh/settings/settings_file.py',
            'dsh/settings/types.py',
            'dsh/typert/__init__.py',
            'dsh/typert/protocol.py',
            'dsh/typert/registry.py',
            'dsh/typert/remote.py',
            'dsh/typert/stores.py']}
SOURCE_INPUTS = CANONICAL_SOURCE_INPUTS | {
    'scripts/llm_metadata_oracle.py', 'scripts/oracles/llm-metadata-fixtures.json',
    'scripts/oracles/llm_metadata_catalog.probe.spec.ts', 'scripts/oracles/llm_metadata_catalog_python.py',
    'scripts/oracles/llm_metadata_stream.probe.spec.ts', 'scripts/oracles/llm_metadata_stream_python.py',
    'scripts/oracles/llm_metadata_python.py', 'scripts/oracles/vitest.llm-metadata-probe.config.mts',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation_digest(rows):
    if not isinstance(rows, list) or len(rows) != len(NAMES) or any(not isinstance(row, dict) for row in rows):
        raise ValueError('LLM metadata complete rows missing')
    if tuple(row.get('name') for row in rows) != NAMES or any(row.get('group') != row['name'].split('/')[0] for row in rows):
        raise ValueError('LLM metadata row identity or order differs')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('LLM metadata Source identity differs')
    if not isinstance(source.get('inputs'), dict) or set(source['inputs']) != SOURCE_INPUTS:
        raise ValueError('LLM metadata Source guard inputs differ')
    if check_files and source['inputs'] != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('LLM metadata Source bytes changed')
    return observation_digest(source['rows'])


def validate_modules(modules, root, required, check_files):
    if __package__:
        from scripts.import_paths import resolve_import_path
    else:
        from import_paths import resolve_import_path
    if not isinstance(modules, dict) or set(modules) != set(required):
        raise ValueError('LLM metadata actual import closure differs')
    missing_prefixes = None if check_files else {}
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('LLM metadata imported path invalid')
        path = resolve_import_path(root, name, missing_prefixes)
        if path.relative_to(root).as_posix() != name or not isinstance(expected, str) or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('LLM metadata imported identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('LLM metadata actual imported bytes differ')


def validate_runtime(report, root, expected_digest, modules, check_files=True):
    root = Path(root).resolve()
    if Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('LLM metadata selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if report.get('modules') != modules:
        raise ValueError('LLM metadata imported bytes differ')
    validate_modules(modules, root, set().union(*GROUP_MODULES.values()), check_files)
    groups = report.get('groups')
    if not isinstance(groups, dict) or set(groups) != set(GROUPS):
        raise ValueError('LLM metadata child groups missing')
    child_rows, child_modules = [], {}
    for group in GROUPS:
        child = groups[group]
        if Path(child['root']).resolve() != root or child.get('executable') != report['executable'] or child.get('python') != report['python']:
            raise ValueError('LLM metadata child runtime differs')
        if not isinstance(child.get('rows'), list) or tuple(row.get('name') for row in child['rows'] if isinstance(row, dict)) != tuple(NAMES_BY_GROUP[group]):
            raise ValueError('LLM metadata child rows incomplete')
        validate_modules(child.get('modules'), root, GROUP_MODULES[group], check_files)
        for name, expected in child['modules'].items():
            if name in child_modules and child_modules[name] != expected:
                raise ValueError('LLM metadata children disagree on bytes')
            child_modules[name] = expected
        child_rows.extend(dict(row, group=group, name=group + '/' + row['name']) for row in child['rows'])
    if child_modules != modules or child_rows != report['rows'] or observation_digest(report['rows']) != expected_digest:
        raise ValueError('LLM metadata complete observations or child aggregate differ')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh LLM metadata outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        inputs = {name: digest(ROOT / name) for name in SOURCE_INPUTS}
        environment = dict(os.environ)
        for group in GROUPS:
            environment['DSH_LLM_METADATA_' + group.upper() + '_OUTPUT'] = str(output.with_suffix('.' + group + '.source.json'))
        completed = subprocess.run(['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run',
            '--config', 'scripts/oracles/vitest.llm-metadata-probe.config.mts'], cwd=str(ROOT), env=environment, capture_output=True, timeout=90)
        output.with_suffix('.source.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError('Actual LLM metadata Source observer failed')
        rows = []
        for group in GROUPS:
            child = json.loads(output.with_suffix('.' + group + '.source.json').read_text(encoding='utf-8'))
            if child['sourceCommit'] != SOURCE_COMMIT or child['node'] != 'v22.22.2' or [row['name'] for row in child['rows']] != NAMES_BY_GROUP[group]:
                raise ValueError('Actual LLM metadata Source child identity or rows differ')
            rows.extend(dict(row, group=group, name=group + '/' + row['name']) for row in child['rows'])
        source = dict(sourceCommit=SOURCE_COMMIT, node='v22.22.2', inputs=inputs, rows=rows)
        with source_path.open('x', encoding='utf-8') as stream:
            json.dump(source, stream, indent=2)
            stream.write('\n')
        expected = identity(source)
        completed = subprocess.run([sys.executable, '-I', 'scripts/oracles/llm_metadata_python.py',
            '--root', str(ROOT), '--output', str(native_path)], cwd=str(ROOT), capture_output=True, timeout=180)
        output.with_suffix('.native.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode or completed.stderr:
            raise RuntimeError('Actual LLM metadata native observer failed')
        native = json.loads(native_path.read_text(encoding='utf-8'))
        validate_runtime(native, ROOT, expected, native['modules'])
        report = dict(status='matched', cases=len(NAMES), observationsSha256=expected)
    except Exception as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
