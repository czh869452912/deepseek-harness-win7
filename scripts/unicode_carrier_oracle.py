import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
NAMES = tuple(name + '/' + carrier for name in ('high', 'low', 'keys', 'pair', 'astral', 'ascii', 'read') for carrier in ('mux', 'rpc', 'llm'))
SOURCE_REQUIRED = {'reference/packages/api/gateway/src/stream-server.ts',
    'reference/packages/client/connection/src/rpc-host.ts', 'reference/packages/client/connection/src/http-bridge.ts',
    'reference/packages/fs/tool-fs/src/read-render.ts', 'reference/packages/llm/llm-deepseek/src/index.ts'}
OBSERVER_INPUTS = ('scripts/unicode_carrier_oracle.py', 'scripts/oracles/unicode_carrier_source.mts',
    'scripts/oracles/unicode_carrier_python.py', 'scripts/unicode_carrier_cases.py',
    'scripts/oracles/deepseek-http.ts', 'scripts/oracles/deepseek_http_python.py')
REQUIRED_IMPORTS = {'dsh/cordis/json_text.py', 'dsh/typert/stream_mux.py', 'dsh/typert/gateway.py',
    'dsh/host/connection/rpc_host.py', 'dsh/host/connection/http_bridge.py', 'dsh/host/webserver/webserver.py',
    'dsh/fs/tool_read_render.py', 'dsh/llm/llm_deepseek.py', 'dsh/llm/llm_service.py'}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inputs(source_root):
    source_root = Path(source_root).resolve()
    pin = subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source_root), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('Unicode carrier Source pin differs or is dirty')
    files = subprocess.check_output(['git', '-C', str(source_root), 'ls-files', '-z'], encoding='utf-8').split('\0')
    inputs = {'reference/' + name: digest(source_root / name) for name in files if name}
    dependency = source_root / 'packages/api/gateway/node_modules/ws'
    for folder, directories, files in os.walk(str(dependency), followlinks=False):
        for name in files:
            path = Path(folder) / name
            inputs['reference/' + path.relative_to(source_root).as_posix()] = digest(path)
    inputs.update({name: digest(ROOT / name) for name in OBSERVER_INPUTS})
    return inputs


def complete_digest(rows):
    if not isinstance(rows, list) or [row.get('name') for row in rows] != list(NAMES):
        raise ValueError('Complete ordered Unicode carrier observations required')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def identity(source, source_root, check_files=True):
    if (not isinstance(source, dict) or set(source) != {'sourceCommit', 'node', 'fixtureSha256', 'rows', 'inputs'}
            or source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2'):
        raise ValueError('Unicode carrier Source runtime differs')
    inputs = source['inputs']
    required = set(OBSERVER_INPUTS) | SOURCE_REQUIRED
    if not isinstance(inputs, dict) or not required.issubset(inputs):
        raise ValueError('Unicode carrier Source input identity missing')
    for name, expected in inputs.items():
        if (not isinstance(name, str) or '\\' in name or ':' in name or '..' in PurePosixPath(name).parts
                or PurePosixPath(name).as_posix() != name or not (name.startswith('reference/') or name in OBSERVER_INPUTS)
                or not isinstance(expected, str) or len(expected) != 64
                or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('Unicode carrier Source input identity invalid')
    if source['fixtureSha256'] != inputs['scripts/oracles/unicode_carrier_source.mts']:
        raise ValueError('Unicode carrier Source observer bytes differ')
    if check_files and inputs != source_inputs(source_root):
        raise ValueError('Unicode carrier Source guarded bytes changed')
    return complete_digest(source['rows'])


def validate_runtime(report, root, executable, source, modules, check_files=True, owned_runtime=False):
    root, executable = Path(root).resolve(), Path(executable).resolve()
    if (not isinstance(report, dict) or set(report) != {'root', 'python', 'executable', 'imports', 'rows', 'fixtureSha256'}
            or report.get('root') != str(root) or not report.get('python', '').startswith('3.8.10 ')
            or Path(report['executable']).resolve() != executable):
        raise ValueError('Unicode carrier selected root or Python differs')
    if owned_runtime and executable != root / 'python.exe':
        raise ValueError('Unicode carrier interpreter must belong to the selected portable')
    if report['fixtureSha256'] != source['inputs']['scripts/oracles/unicode_carrier_python.py']:
        raise ValueError('Unicode carrier native observer bytes differ')
    if not isinstance(modules, dict) or not REQUIRED_IMPORTS.issubset(modules) or report['imports'] != modules:
        raise ValueError('Unicode carrier actual imported closure differs')
    for name, expected in modules.items():
        if (not isinstance(name, str) or not name.startswith('dsh/') or '\\' in name or ':' in name
                or '..' in PurePosixPath(name).parts or PurePosixPath(name).as_posix() != name
                or not isinstance(expected, str) or len(expected) != 64
                or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('Unicode carrier imported identity invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or check_files and digest(path) != expected:
            raise ValueError('Unicode carrier actual imported bytes differ')
    if complete_digest(report['rows']) != identity(source, ROOT / 'reference', check_files=False):
        raise ValueError('Unicode carrier complete public observations differ')


def observe_native(root, executable, output):
    root, executable, output = Path(root).resolve(), Path(executable).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh Unicode carrier native output required')
    completed = subprocess.run([str(executable), '-I', str(ROOT / 'scripts/oracles/unicode_carrier_python.py'),
        str(root), str(output)], cwd=str(output.parent), capture_output=True, timeout=90)
    output.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
    if completed.returncode or completed.stderr:
        raise RuntimeError('Actual Unicode carrier native observer failed')
    return json.loads(output.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh Unicode carrier outputs required')
    result = dict(status='runner-error')
    try:
        inputs = source_inputs(ROOT / 'reference')
        environment = dict(os.environ, DSH_UNICODE_CARRIER_OUTPUT=str(source_path),
                           TSX_TSCONFIG_PATH=str(ROOT / 'reference/tsconfig.json'))
        completed = subprocess.run(['node', '--import', (ROOT / 'reference/node_modules/tsx/dist/loader.mjs').as_uri(),
            str(ROOT / 'scripts/oracles/unicode_carrier_source.mts')], cwd=str(ROOT), env=environment,
            capture_output=True, timeout=90)
        output.with_suffix('.source.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError('Actual Unicode carrier Source observer failed')
        if source_inputs(ROOT / 'reference') != inputs:
            raise ValueError('Unicode carrier Source inputs changed during observation')
        source = json.loads(source_path.read_text(encoding='utf-8'))
        source['inputs'] = inputs
        source_path.write_text(json.dumps(source, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        expected = identity(source, ROOT / 'reference')
        native = observe_native(ROOT, sys.executable, native_path)
        validate_runtime(native, ROOT, sys.executable, source, native['imports'])
        result = dict(status='matched', cases=len(NAMES), observationsSha256=expected)
    except Exception as error:
        result['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return 0 if result['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
