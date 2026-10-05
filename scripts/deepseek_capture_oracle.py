import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
sys.path.insert(0, str(ROOT))
from scripts.oracles.deepseek_capture_python import NAMES
from dsh.core.session.json import walk_json_value
SOURCE_INPUTS = {'scripts/oracles/deepseek_capture_http.ts', 'reference/packages/llm/llm/src/retry-policy.ts', 'scripts/oracles/deepseek_capture_settings.ts', 'reference/packages/llm/llm-deepseek/src/sse.ts', 'reference/packages/llm/llm-deepseek/src/translate.ts', 'scripts/oracles/deepseek-fixtures.json', 'reference/packages/llm/llm-deepseek/src/adapter.ts', 'scripts/oracles/deepseek_capture_files.ts', 'scripts/oracles/vitest.deepseek-capture-probe.config.mts', 'reference/packages/llm/llm-retry/src/index.ts', 'migration/modules.json', 'scripts/oracles/vitest.deepseek-probe.config.mts', 'reference/packages/llm/llm-deepseek/src/files-api.ts', 'reference/packages/llm/llm-deepseek/src/serialize.ts', 'scripts/oracles/deepseek_capture.probe.spec.ts', 'reference/packages/llm/llm-deepseek/src/index.ts'}
REQUIRED_MODULES = {'dsh/llm/llm_deepseek.py', 'dsh/llm/deepseek_wire.py',
    'dsh/llm/deepseek_request.py', 'dsh/llm/deepseek_config.py', 'dsh/llm/llm_service.py',
    'dsh/llm/http_stream.py', 'dsh/llm/stream_bridge.py', 'dsh/core/abort.py',
    'dsh/cordis/context.py', 'dsh/cordis/utils.py', 'dsh/llm/deepseek_api_extensions.py',
    'dsh/core/session/json.py', 'dsh/llm/retry_policy.py', 'dsh/llm/llm_retry.py',
    'dsh/llm/deepseek_files.py', 'dsh/llm/image_content.py', 'dsh/settings/settings_file.py'}


def canonical_rows(rows):
    aliases = {}
    owners = {}
    for row in rows:
        for event in row.get('value', {}).get('retryEvents', []) if isinstance(row.get('value'), dict) else []:
            selected = event['data']['retryId']
            if not isinstance(selected, str) or str(uuid.UUID(selected)) != selected or uuid.UUID(selected).version != 4:
                raise ValueError('retryId must retain its actual UUID4 form')
            if selected in owners and owners[selected] != row['id']:
                raise ValueError('retryId cannot be shared across independently observed fixtures')
            owners[selected] = row['id']
            if selected not in aliases:
                aliases[selected] = '__observed_retry_chain_' + str(len(aliases))
    def visit(value):
        if isinstance(value, str):
            return aliases.get(value, value)
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, dict):
            return {name: visit(item) for name, item in value.items()}
        return value
    result = visit(rows)
    for row in result:
        value = row.get('value')
        if not isinstance(value, dict) or 'originPort' not in value:
            continue
        port, origin = value['originPort'], value.get('origin')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Observed loopback port is invalid')
        endpoint = 'http://127.0.0.1:' + str(port)
        if not isinstance(origin, dict) or type(origin.get('port')) is not int or origin != dict(host='127.0.0.1', port=port, baseURL=endpoint):
            raise ValueError('Observed listener and configured origin differ')
        def origin_value(current):
            if isinstance(current, str):
                return re.sub(re.escape(endpoint) + r'(?=$|[^0-9])', '__observed_loopback_origin__', current)
            if isinstance(current, list):
                return [origin_value(item) for item in current]
            if isinstance(current, dict):
                return {name: origin_value(item) for name, item in current.items()}
            return current
        normalized = origin_value(value)
        normalized['originPort'] = '__observed_loopback_port__'
        normalized['origin']['port'] = '__observed_loopback_port__'
        row['value'] = normalized
    return result, aliases


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observation_digest(rows):
    if not isinstance(rows, list) or tuple(row['id'] for row in rows) != NAMES:
        raise ValueError('DeepSeek capture observations are missing, duplicate or reordered')
    invalid = object()
    canonical, _ = canonical_rows(rows)
    values = walk_json_value(canonical, detach=True, undefined_sentinel=invalid)
    if values is invalid:
        raise ValueError('DeepSeek capture observations are not lossless JSON values')
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('DeepSeek capture Source identity differs')
    inputs = source.get('inputs')
    if not isinstance(inputs, dict) or set(inputs) != SOURCE_INPUTS:
        raise ValueError('DeepSeek capture Source guard inputs differ')
    if check_files and inputs != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('DeepSeek capture Source guard bytes changed')
    return observation_digest(source['rows'])


def validate_executable(executable, root, check_files=True):
    root = Path(root).resolve()
    selected = Path(sys.executable).resolve() if root == ROOT and check_files else (root / 'python.exe').resolve()
    if Path(executable).resolve() != selected:
        raise ValueError('Observer executable is not the selected interpreter')
    selected.relative_to(root)


def validate_runtime(report, root, expected_digest, modules, check_files=True):
    root = Path(root).resolve()
    if not isinstance(report, dict) or Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('DeepSeek capture selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or report['modules'] != modules:
        raise ValueError('DeepSeek capture actual imported module closure differs')
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('DeepSeek capture module path invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('DeepSeek capture module identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('DeepSeek capture actual imported bytes differ')
    if observation_digest(report['rows']) != expected_digest:
        raise ValueError('DeepSeek capture complete HTTP observations differ')


def source_pin():
    pin = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('DeepSeek capture Source pin differs or is dirty')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh paired DeepSeek capture outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        environment = dict(os.environ, DSH_DEEPSEEK_CAPTURE_OUTPUT=str(source_path))
        commands = [
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config',
                'scripts/oracles/vitest.deepseek-capture-probe.config.mts'],
            [sys.executable, '-I', 'scripts/oracles/deepseek_capture_python.py', '--root', str(ROOT), '--source', str(source_path), '--output', str(native_path)],
        ]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=60)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError('DeepSeek capture observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        source_digest = identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules = {name: digest(ROOT / name) for name in native['modules']}
        validate_runtime(native, ROOT, source_digest, modules)
        source_pin()
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
            observations_sha256=source_digest, modules=modules,
            scope='76 actual pinned/native loopback config/model/serialize/usage/SSE/HTTP/Files/Settings captures retain every observed field and exact selected error name/message/failure/quota/status. HTTP/Files independently allocate actual listeners and retain coherent host/port/configured endpoint facts. Only these declared allocation identities map across all captured value occurrences; raw ports/URLs and complete failure prose stay retained. Opaque UUID4 retry identities map bijectively across all occurrences in all rows, preserving chains and cross-fixture uniqueness. Whole JSON integer numeric spellings normalize solely for digest. Actual Source retry plugin and native retry plugin use a controlled recovery probe, not canonical AgentLoop. Extra exception cause/stack/properties and internal settings fallback diagnostics, immutable/public graph ABI, arbitrary malformed transport/cancellation/reentry, full profiles, paid/cloud/OAuth and Win7 remain open. Selected/extracted Python3.8.10 with every actual imported module byte is mandatory. Raw stdout/stderr are retained, including expected native last-good configuration logs; no Source failure bypass.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
