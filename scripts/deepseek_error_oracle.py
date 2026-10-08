import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
sys.path.insert(0, str(ROOT))
from scripts.oracles.deepseek_error_python import NAMES
from dsh.core.session.json import walk_json_value
SOURCE_INPUTS = {
    'reference/packages/llm/llm-deepseek/src/index.ts', 'reference/packages/llm/llm-deepseek/src/adapter.ts',
    'reference/packages/llm/llm-deepseek/src/translate.ts', 'reference/packages/llm/llm-deepseek/src/sse.ts',
    'scripts/oracles/deepseek_error_http.ts', 'scripts/oracles/deepseek_error.probe.spec.ts',
    'scripts/oracles/vitest.deepseek-error-probe.config.mts', 'scripts/oracles/deepseek-error-fixtures.json',
    'scripts/oracles/vitest.deepseek-probe.config.mts', 'migration/modules.json',
} | {'scripts/import_paths.py'}
REQUIRED_MODULES = {'dsh/llm/llm_deepseek.py', 'dsh/llm/deepseek_wire.py',
    'dsh/llm/deepseek_request.py', 'dsh/llm/deepseek_config.py', 'dsh/llm/llm_service.py',
    'dsh/llm/http_stream.py', 'dsh/llm/stream_bridge.py', 'dsh/core/abort.py',
    'dsh/cordis/context.py', 'dsh/cordis/utils.py', 'dsh/llm/deepseek_api_extensions.py',
    'dsh/core/session/json.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation_digest(rows):
    if not isinstance(rows, list) or tuple(row['name'] for row in rows) != NAMES:
        raise ValueError('DeepSeek error observations are missing, duplicate or reordered')
    invalid = object()
    values = walk_json_value(rows, detach=True, undefined_sentinel=invalid)
    if values is invalid:
        raise ValueError('DeepSeek error observations are not lossless JSON values')
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('DeepSeek error Source identity differs')
    inputs = source.get('inputs')
    if not isinstance(inputs, dict) or set(inputs) != SOURCE_INPUTS:
        raise ValueError('DeepSeek error Source guard inputs differ')
    if check_files and inputs != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('DeepSeek error Source guard bytes changed')
    return observation_digest(source['rows'])


def validate_executable(executable, root, check_files=True):
    root = Path(root).resolve()
    selected = Path(sys.executable).resolve() if root == ROOT and check_files else (root / 'python.exe').resolve()
    if Path(executable).resolve() != selected:
        raise ValueError('Observer executable is not the selected interpreter')
    selected.relative_to(root)


def validate_runtime(report, root, expected_digest, modules, check_files=True):
    if __package__:
        from scripts.import_paths import resolve_import_path
    else:
        from import_paths import resolve_import_path
    root = Path(root).resolve()
    if not isinstance(report, dict) or Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('DeepSeek error selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or report['modules'] != modules:
        raise ValueError('DeepSeek error actual imported module closure differs')
    missing_prefixes = None if check_files else {}
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('DeepSeek error module path invalid')
        path = resolve_import_path(root, name, missing_prefixes)
        if path.relative_to(root).as_posix() != name or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('DeepSeek error module identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('DeepSeek error actual imported bytes differ')
    if observation_digest(report['rows']) != expected_digest:
        raise ValueError('DeepSeek error complete HTTP observations differ')


def source_pin():
    pin = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('DeepSeek error Source pin differs or is dirty')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh paired DeepSeek error outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        environment = dict(os.environ, DSH_DEEPSEEK_ERROR_OUTPUT=str(source_path))
        commands = [
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config',
                'scripts/oracles/vitest.deepseek-error-probe.config.mts'],
            [sys.executable, '-I', 'scripts/oracles/deepseek_error_python.py', '--root', str(ROOT), '--output', str(native_path)],
        ]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=60)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            if result.returncode or result.stderr:
                raise RuntimeError('DeepSeek error observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        source_digest = identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules = {name: digest(ROOT / name) for name in native['modules']}
        validate_runtime(native, ROOT, source_digest, modules)
        source_pin()
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
            observations_sha256=source_digest, modules=modules,
            scope='24 actual original/native loopback HTTP adapter consumers compare every captured request, chunk, extension acceptance and error name/message/failure/code/status/retry-after/request-id value. Flattened status/retry-after/request-id are observed from the complete actual failure object on both sides; no extra language exception-property parity is claimed. Every field/value is retained; no prose filtering or identity mapping. The existing lossless JSON snapshot provider canonicalizes semantically identical whole-number token spellings such as2000/2000.0 solely for digesting; all raw reports remain unchanged. Malformed previews use Source120 UTF16 units including a split surrogate; idle messages include Source number rendering of configured whole/fractional milliseconds. Selected/extracted ownPython3.8.10 and actual imported native module bytes are mandatory. Adapter dependencies are controlled fixture inputs, not full Cordis provider/profile boot. Static Source guards do not establish complete dynamic import closure; frozen full inputs bind wider sources. Retry orchestration, arbitrary malformed graphs/transport/cancellation schedules, images/files, cloud/OAuth/paid service, full AgentLoop/profiles and realWin7 remain open.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
