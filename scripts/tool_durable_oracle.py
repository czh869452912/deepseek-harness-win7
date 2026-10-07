import argparse
import copy
import re
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
NAMES = ('success-absent', 'success-null', 'success-false', 'success-zero', 'success-empty-object', 'success-empty-array', 'success-unicode', 'success-graph', 'plain-failure', 'typed-failure', 'abort-before', 'abort-after-first')
OBSERVER_INPUTS = ('scripts/tool_durable_oracle.py', 'scripts/oracles/tool_durable_source.mts',
                   'scripts/oracles/tool_durable_python.py', 'scripts/tool_durable_cases.py', 'scripts/oracles/tool-durable-cases.json')
REQUIRED_IMPORTS = {'dsh/core/tools.py', 'dsh/core/system_prompt/__init__.py', 'dsh/core/tool_calls.py', 'dsh/llm/message.py', 'dsh/llm/llm_service.py', 'dsh/cordis/context.py',
                    'dsh/core/abort.py', 'dsh/llm/error.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inputs(source_root):
    source_root = Path(source_root).resolve()
    pin = subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source_root), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('Durable tool Source pin differs or is dirty')
    files = subprocess.check_output(['git', '-C', str(source_root), 'ls-files', '-z'], encoding='utf-8').split('\0')
    inputs = {'reference/' + name: digest(source_root / name) for name in files if name}
    inputs.update({name: digest(ROOT / name) for name in OBSERVER_INPUTS})
    return inputs


def complete_digest(rows):
    if not isinstance(rows, list) or [row.get('name') for row in rows] != list(NAMES):
        raise ValueError('Complete ordered Durable tool observations required')
    selected = copy.deepcopy(rows)
    identities = set()
    for row in selected:
        for position, event in enumerate(row['events']):
            if event['type'] != 'tool/result':
                continue
            identity = event['data']['message']['id']
            if not isinstance(identity, str) or not re.fullmatch(
                    r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', identity):
                raise ValueError('Full UUIDv4 tool-result allocations required')
            if identity in identities:
                raise ValueError('Distinct tool-result allocations required')
            identities.add(identity)
            event['data']['message']['id'] = 'tool-result-' + row['name'] + '-' + str(position)
    return hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def identity(source, source_root, check_files=True):
    if (not isinstance(source, dict) or set(source) != {'sourceCommit', 'node', 'fixtureSha256', 'rows', 'inputs'}
            or source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2'):
        raise ValueError('Durable tool Source runtime differs')
    inputs = source['inputs']
    required = set(OBSERVER_INPUTS) | {'reference/packages/core/tools/src/index.ts', 'reference/packages/core/agent-loop/src/tool-calls.ts', 'reference/packages/llm/llm/src/message.ts'}
    if not isinstance(inputs, dict) or not required.issubset(inputs):
        raise ValueError('Durable tool Source input identity missing')
    for name, expected in inputs.items():
        if (not isinstance(name, str) or '\\' in name or ':' in name or '..' in PurePosixPath(name).parts
                or PurePosixPath(name).as_posix() != name or not (name.startswith('reference/') or name in OBSERVER_INPUTS)
                or not isinstance(expected, str) or len(expected) != 64
                or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('Durable tool Source input identity invalid')
    if source['fixtureSha256'] != inputs['scripts/oracles/tool_durable_source.mts']:
        raise ValueError('Durable tool Source observer bytes differ')
    if check_files and inputs != source_inputs(source_root):
        raise ValueError('Durable tool Source guarded bytes changed')
    return complete_digest(source['rows'])


def validate_runtime(report, root, executable, source, modules, check_files=True, owned_runtime=False):
    root, executable = Path(root).resolve(), Path(executable).resolve()
    if (not isinstance(report, dict) or set(report) != {'root', 'python', 'executable', 'imports', 'rows', 'fixtureSha256'}
            or report.get('root') != str(root) or not report.get('python', '').startswith('3.8.10 ')
            or Path(report['executable']).resolve() != executable):
        raise ValueError('Durable tool selected root or Python differs')
    if owned_runtime and executable != root / 'python.exe':
        raise ValueError('Durable tool interpreter must belong to the selected portable')
    if report['fixtureSha256'] != source['inputs']['scripts/oracles/tool_durable_python.py']:
        raise ValueError('Durable tool native observer bytes differ')
    if not isinstance(modules, dict) or not REQUIRED_IMPORTS.issubset(modules) or report['imports'] != modules:
        raise ValueError('Durable tool actual imported closure differs')
    for name, expected in modules.items():
        if (not isinstance(name, str) or not name.startswith('dsh/') or '\\' in name or ':' in name
                or '..' in PurePosixPath(name).parts or PurePosixPath(name).as_posix() != name
                or not isinstance(expected, str) or len(expected) != 64
                or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('Durable tool imported identity invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or check_files and digest(path) != expected:
            raise ValueError('Durable tool actual imported bytes differ')
    if complete_digest(report['rows']) != identity(source, ROOT / 'reference', check_files=False):
        raise ValueError('Durable tool complete public observations differ')


def observe_native(root, executable, output):
    root, executable, output = Path(root).resolve(), Path(executable).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh Durable tool native output required')
    completed = subprocess.run([str(executable), '-I', str(ROOT / 'scripts/oracles/tool_durable_python.py'),
        '--root', str(root), '--output', str(output)], cwd=str(output.parent), capture_output=True, timeout=90)
    output.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
    if completed.returncode or completed.stderr:
        raise RuntimeError('Actual Durable tool native observer failed')
    return json.loads(output.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh Durable tool outputs required')
    result = dict(status='runner-error')
    try:
        inputs = source_inputs(ROOT / 'reference')
        environment = dict(os.environ, DSH_TOOL_DURABLE_OUTPUT=str(source_path),
                           TSX_TSCONFIG_PATH=str(ROOT / 'reference/tsconfig.json'))
        completed = subprocess.run(['node', '--import', (ROOT / 'reference/node_modules/tsx/dist/loader.mjs').as_uri(),
            str(ROOT / 'scripts/oracles/tool_durable_source.mts')], cwd=str(ROOT), env=environment,
            capture_output=True, timeout=90)
        output.with_suffix('.source.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError('Actual Durable tool Source observer failed')
        if source_inputs(ROOT / 'reference') != inputs:
            raise ValueError('Durable tool Source inputs changed during observation')
        source = json.loads(source_path.read_text(encoding='utf-8'))
        source['inputs'] = inputs
        source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
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
