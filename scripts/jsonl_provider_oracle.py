import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sqlite_provider_oracle import hashes, normalize
from scripts.sqlite_format_oracle import ASSETS as FORMAT_ASSETS, digest

MODULES = ['dsh/session/persistence_jsonl_canonical.py', 'dsh/session/jsonl_store.py',
    'dsh/session/jsonl_format.py', 'dsh/session/jsonl_zstd.py', 'dsh/session/zstd.py',
    'dsh/session/sqlite_codec.py', 'dsh/session/sqlite_json.py', 'dsh/session/sqlite_logical.py',
    'dsh/session/seq_ranges.py', 'dsh/session/file_revision.py', 'dsh/session/durable_publish.py',
    'dsh/session/persistence.py', 'dsh/session/coordinator.py', 'dsh/session/prepared_persistence.py',
    'dsh/session/preparations.py', 'dsh/session/live_persistence.py', 'dsh/session/write_behind.py',
    'dsh/core/session/types.py', 'dsh/core/session/json.py', 'dsh/core/session/__init__.py',
    'dsh/core/session/session.py', 'dsh/core/session/preparation.py', 'dsh/core/session/repair.py',
    'dsh/session/repair.py', 'dsh/boot/plugin_registry.py', 'dsh/session/__init__.py']
ASSETS = ['dsh/session/bin/zstd/' + name for name in FORMAT_ASSETS]
KEYS = [compression + '-' + str(pack).lower() for compression in ('zstd', 'none') for pack in (True, False)]
INPUTS = MODULES + ASSETS + ['scripts/jsonl_provider_oracle.py', 'scripts/oracles/jsonl_provider_python.py',
    'scripts/oracles/jsonl_provider.probe.spec.ts', 'scripts/oracles/jsonl_frames.mjs',
    'scripts/oracles/vitest.jsonl-provider-probe.config.mts', 'scripts/oracles/vitest.jsonl-provider-source.config.mts'] + [
    'reference/packages/session/session-persistence-jsonl/src/' + name + '.ts'
    for name in ('index', 'format', 'zstd', 'zstd-public-decoder', 'zstd-private-decoder', 'win32', 'invariant')]


def observation_digest(rows):
    if not isinstance(rows, list) or len(rows) != 579 or any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in rows):
        raise ValueError('JSONL observations are incomplete')
    identities = [row['id'] for row in rows]
    if len(set(identities)) != len(identities):
        raise ValueError('JSONL observations are duplicated')
    if identities[561:] != ['materialization/' + key for key in KEYS] + ['mutual/' + key for key in KEYS] + ['cross-frame/' + str(index) for index in range(10)]:
        raise ValueError('JSONL provider observation order differs')
    families = {'frame': 10, 'cut': 285, 'checksum': 10, 'descriptor': 256}
    for prefix, count in families.items():
        if sum(identity.startswith(prefix + '/') for identity in identities[:561]) != count:
            raise ValueError('JSONL frame fixture family differs')
    return digest(rows)


def source_identity(source):
    if not isinstance(source, dict) or set(source) != {'node', 'rows'} or source['node'] != 'v22.22.2':
        raise ValueError('Pinned JSONL Source runtime differs')
    return observation_digest(source['rows'])


def validate_runtime(report, root=None, expected_digest=None, expected_inputs=None, expected_modules=None, expected_assets=None):
    if not isinstance(report, dict) or set(report) != {'root', 'python', 'moduleFile', 'modules', 'assets', 'generatedInputsSha256', 'rows'}:
        raise ValueError('JSONL runtime receipt is incomplete')
    root = Path(root if root is not None else report['root']).resolve()
    if report['root'] != str(root) or report['python'] != '3.8.10' or report['moduleFile'] != str(root / 'dsh/session/jsonl_store.py'):
        raise ValueError('JSONL runtime provenance differs')
    for field, paths, supplied in (('modules', MODULES, expected_modules), ('assets', ASSETS, expected_assets)):
        expected = hashes(root, paths) if supplied is None else supplied
        if not isinstance(expected, dict) or set(expected) != set(paths) or report[field] != expected or any(not re.fullmatch('[0-9a-f]{64}', value) for value in expected.values()):
            raise ValueError('JSONL owned module/resource closure differs')
    for actual, expected in ((observation_digest(report['rows']), expected_digest), (report['generatedInputsSha256'], expected_inputs)):
        if not isinstance(actual, str) or not re.fullmatch('[0-9a-f]{64}', actual) or expected is not None and actual != expected:
            raise ValueError('JSONL observations/inputs differ from actual Source')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--python', type=Path)
    parser.add_argument('--environment', type=Path)
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    workspace = output.with_name(output.stem + '.workspace')
    if output.exists() or workspace.exists():
        raise ValueError('JSONL qualification requires fresh output and workspace')
    product = arguments.root.resolve() if arguments.root else ROOT
    python = str(arguments.python.resolve()) if arguments.python else sys.executable
    report = dict(status='failed')
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if target != actual or dirty:
            raise ValueError('JSONL requires the unchanged pinned Source')
        report.update(target_upstream=target, inputSha256=hashes(ROOT, INPUTS))
        workspace.mkdir()
        environment = dict(os.environ, JSONL_PROVIDER_DIRECTORY=str(workspace))
        node = shutil.which('node')
        if node is None:
            raise ValueError('JSONL qualification requires pinned Node')
        sequence = 0
        def run(command, native=False):
            nonlocal sequence
            selected = json.loads(arguments.environment.read_text(encoding='utf-8')) if native and arguments.environment else environment
            result = subprocess.run(command, cwd=str(workspace) if native else str(ROOT), env=selected, capture_output=True, timeout=120)
            output.with_name(output.stem + '.' + str(sequence) + '.log').write_bytes(result.stdout + result.stderr)
            sequence += 1
            if result.returncode:
                raise ValueError('JSONL observer failed: ' + str(sequence - 1))
        frame_command = [node, '--experimental-transform-types', str(ROOT / 'scripts/oracles/jsonl_frames.mjs'), str(workspace / 'frames')]
        run(frame_command + ['produce'])
        probe_command = [node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run', '--config', str(ROOT / 'scripts/oracles/vitest.jsonl-provider-probe.config.mts')]
        environment['JSONL_PROVIDER_PHASE'] = 'produce'
        run(probe_command)
        produced = json.loads((workspace / 'source-produce.json').read_text(encoding='utf-8'))
        fixtures = [{key: item[key] for key in ('key', 'compression', 'packChunks', 'metadata', 'events')} for item in produced['inputs']]
        inputs = dict(modules=MODULES, assets=ASSETS, providerFixtures=fixtures, generated=hashes(workspace,
            ['frames/source.json'] + ['frames/' + prefix + '-' + str(index) + '.bin'
                for prefix in ('plain', 'frame') for index in range(10)]))
        input_path = output.with_name(output.stem + '.inputs.json')
        input_path.write_text(json.dumps(inputs, ensure_ascii=True), encoding='utf-8')
        native_path = output.with_name(output.stem + '.native.json')
        run([python, '-I', str(ROOT / 'scripts/oracles/jsonl_provider_python.py'), '--root', str(product),
            '--directory', str(workspace), '--inputs', str(input_path), '--output', str(native_path)], native=True)
        environment['JSONL_PROVIDER_PHASE'] = 'consume'
        run(probe_command)
        run(frame_command + ['consume'])
        frames = json.loads((workspace / 'frames/source.json').read_text(encoding='utf-8'))
        produced = json.loads((workspace / 'source-produce.json').read_text(encoding='utf-8'))
        consumed = json.loads((workspace / 'source-consume.json').read_text(encoding='utf-8'))
        cross = json.loads((workspace / 'frames/source-consume.json').read_text(encoding='utf-8'))
        if any(value.get('node') not in ('22.22.2', 'v22.22.2') for value in (frames, produced, consumed, cross)):
            raise ValueError('JSONL observers use a different Node')
        source = dict(node='v22.22.2', rows=normalize(frames['rows'] + produced['rows'] + consumed['rows'] + cross['rows'], workspace))
        source_path = output.with_name(output.stem + '.source.json')
        source_path.write_text(json.dumps(source, ensure_ascii=True), encoding='utf-8')
        native = json.loads(native_path.read_text(encoding='utf-8'))
        native['rows'] = normalize(native['rows'], workspace)
        native_path.write_text(json.dumps(native, ensure_ascii=True), encoding='utf-8')
        expected, generated = source_identity(source), hashlib.sha256(input_path.read_bytes()).hexdigest()
        validate_runtime(native, product, expected, generated)
        if native['rows'] != source['rows'] or report['inputSha256'] != hashes(ROOT, INPUTS):
            raise ValueError('JSONL observations/owned inputs changed')
        report.update(status='passed', cases=579, observationsSha256=expected, generatedInputsSha256=generated,
            modules=native['modules'], assets=native['assets'], nativeRoot=str(product),
            scope='Bounded checksummed frames/UTF16 paths and actual Source/native mutual files, revisions, raw export, cold preparation; arbitrary histories/competition and real Win7 remain unaccepted.')
    except Exception as error:
        report['failure'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
