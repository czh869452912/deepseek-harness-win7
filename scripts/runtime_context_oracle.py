import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
NAMES = ('change', 'clear', 'same', 'empty')
SOURCE_INPUTS = {
    'reference/packages/core/agent-loop/src/agent.ts',
    'reference/packages/core/agent-loop/src/runtime-context.ts',
    'reference/packages/core/system-prompt/src/index.ts',
    'reference/packages/core/agent-loop/tests/mock-adapter.ts',
    'scripts/oracles/runtime_context.probe.spec.ts',
    'scripts/oracles/vitest.runtime-context-probe.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts',
    'migration/modules.json',
}
REQUIRED_MODULES = {'dsh/core/agent_loop.py', 'dsh/core/runtime_context.py',
    'dsh/core/system_prompt/types.py', 'dsh/core/system_prompt/__init__.py',
    'dsh/core/session/session.py', 'dsh/core/tools.py', 'dsh/cordis/context.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(row):
    identities = {}

    def snapshot(message):
        value = copy.deepcopy(message)
        identity = value['id']
        if not isinstance(identity, str) or not identity:
            raise ValueError('Runtime context message identity missing')
        if identity not in identities:
            identities[identity] = 'context-' + str(len(identities) + 1)
        value['id'] = identities[identity]
        return value

    if len(row['requests']) != 2:
        raise ValueError('Runtime context requires both actual model requests')
    requests = []
    for request in row['requests']:
        contexts = [message for message in request['messages'] if isinstance(message, dict)
            and message.get('source', {}).get('plugin') == '@deepseek-ai/dsh-system-prompt']
        requests.append([snapshot(message) for message in contexts])
    return dict(name=row['name'], requests=requests, snapshots=[snapshot(message) for message in row['snapshots']])


def observation_digest(observations):
    if not isinstance(observations, list) or tuple(row['name'] for row in observations) != NAMES:
        raise ValueError('Runtime context observations are missing, duplicate or reordered')
    rows = [canonical(row) for row in observations]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('Runtime context Source identity differs')
    inputs = source.get('inputs')
    if not isinstance(inputs, dict) or set(inputs) != SOURCE_INPUTS:
        raise ValueError('Runtime context Source guard inputs differ')
    if check_files and inputs != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('Runtime context Source guard bytes changed')
    return observation_digest(source['observations'])


def validate_runtime(report, root, expected_digest, modules, check_files=True):
    root = Path(root).resolve()
    if not isinstance(report, dict) or Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('Runtime context selected root or Python differs')
    Path(report['executable']).resolve().relative_to(root)
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or report['modules'] != modules:
        raise ValueError('Runtime context actual imported module closure differs')
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('Runtime context module path invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('Runtime context module identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('Runtime context actual imported bytes differ')
    if observation_digest(report['observations']) != expected_digest:
        raise ValueError('Runtime context complete attributed messages differ')


def source_pin():
    pin = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('Runtime context Source pin differs or is dirty')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh paired runtime context outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        environment = dict(os.environ, DSH_RUNTIME_CONTEXT_OUTPUT=str(source_path))
        commands = [
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config',
                'scripts/oracles/vitest.runtime-context-probe.config.mts'],
            [sys.executable, '-I', 'scripts/oracles/runtime_context_python.py', '--root', str(ROOT), '--output', str(native_path)],
        ]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=60)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            if result.returncode or result.stderr:
                raise RuntimeError('Runtime context observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        source_digest = identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules = {name: digest(ROOT / name) for name in native['modules']}
        validate_runtime(native, ROOT, source_digest, modules)
        source_pin()
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
            observations_sha256=source_digest, modules=modules,
            scope='Four real AgentLoop model/tool/next-step consumers; complete attributed runtime-context and durable messages with correlated opaque message identities. Other raw model fields, arbitrary contexts/profiles, complete B3/C2 and real Win7 remain unqualified.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
