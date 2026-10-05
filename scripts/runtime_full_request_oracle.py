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
sys.path.insert(0, str(ROOT))
from scripts.oracles.runtime_full_request_python import NAMES
SOURCE_INPUTS = {
    'reference/packages/core/agent-loop/src/agent.ts',
    'reference/packages/core/agent-loop/src/runtime-context.ts',
    'reference/packages/core/system-prompt/src/index.ts',
    'reference/packages/core/agent-loop/tests/mock-adapter.ts',
    'scripts/oracles/runtime_full_request.probe.spec.ts',
    'scripts/oracles/vitest.runtime-full-request-probe.config.mts',
    'scripts/oracles/vitest.consumers.config.mts', 'scripts/oracles/vitest.core.config.mts',
    'migration/modules.json',
    'reference/packages/llm/llm/src/index.ts', 'reference/packages/llm/llm/src/types.ts',
}
REQUIRED_MODULES = {'dsh/core/agent_loop.py', 'dsh/core/runtime_context.py',
    'dsh/core/system_prompt/types.py', 'dsh/core/system_prompt/__init__.py',
    'dsh/core/session/session.py', 'dsh/core/tools.py', 'dsh/cordis/context.py',
    'dsh/core/agent.py', 'dsh/core/abort.py', 'dsh/llm/llm_service.py'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(row):
    result = copy.deepcopy(row)
    identities = {}

    def message(selected):
        identity_value = selected['id']
        if not isinstance(identity_value, str) or not identity_value:
            raise ValueError('Runtime full request message identity missing')
        if identity_value not in identities:
            identities[identity_value] = 'message-' + str(len(identities) + 1)
        selected['id'] = identities[identity_value]

    if len(result['requests']) != 2:
        raise ValueError('Both actual model requests are required')
    for request in result['requests']:
        for selected in request['messages']:
            message(selected)
    for selected in result['snapshots']:
        message(selected)
    return result


def observation_digest(observations):
    if not isinstance(observations, list) or tuple(row['name'] for row in observations) != NAMES:
        raise ValueError('Runtime full request observations are missing, duplicate or reordered')
    rows = [canonical(row) for row in observations]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True,
        allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def identity(source, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('Runtime full request Source identity differs')
    inputs = source.get('inputs')
    if not isinstance(inputs, dict) or set(inputs) != SOURCE_INPUTS:
        raise ValueError('Runtime full request Source guard inputs differ')
    if check_files and inputs != {name: digest(ROOT / name) for name in SOURCE_INPUTS}:
        raise ValueError('Runtime full request Source guard bytes changed')
    return observation_digest(source['observations'])


def validate_executable(executable, root, check_files=True):
    root = Path(root).resolve()
    selected = Path(sys.executable).resolve() if root == ROOT and check_files else (root / 'python.exe').resolve()
    if Path(executable).resolve() != selected:
        raise ValueError('Observer executable is not the selected interpreter')
    selected.relative_to(root)


def validate_runtime(report, root, expected_digest, modules, check_files=True):
    root = Path(root).resolve()
    if not isinstance(report, dict) or Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('Runtime full request selected root or Python differs')
    validate_executable(report['executable'], root, check_files)
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or report['modules'] != modules:
        raise ValueError('Runtime full request actual imported module closure differs')
    for name, expected in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('Runtime full request module path invalid')
        path = (root / name).resolve()
        if path.relative_to(root).as_posix() != name or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected):
            raise ValueError('Runtime full request module identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('Runtime full request actual imported bytes differ')
    if observation_digest(report['observations']) != expected_digest:
        raise ValueError('Runtime full request complete model request graphs differ')


def source_pin():
    pin = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('Runtime full request Source pin differs or is dirty')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    if any(path.exists() for path in (output, source_path, native_path)):
        raise ValueError('Fresh paired runtime full request outputs required')
    report = dict(status='runner-error')
    try:
        source_pin()
        environment = dict(os.environ, DSH_RUNTIME_FULL_REQUEST_OUTPUT=str(source_path))
        commands = [
            ['node', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config',
                'scripts/oracles/vitest.runtime-full-request-probe.config.mts'],
            [sys.executable, '-I', 'scripts/oracles/runtime_full_request_python.py', '--root', str(ROOT), '--output', str(native_path)],
        ]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=60)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            if result.returncode or result.stderr:
                raise RuntimeError('Runtime full request observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        source_digest = identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        modules = {name: digest(ROOT / name) for name in native['modules']}
        validate_runtime(native, ROOT, source_digest, modules)
        source_pin()
        report.update(status='matched', target_upstream=SOURCE_COMMIT, cases=len(NAMES),
            observations_sha256=source_digest, modules=modules,
            scope='Sixteen actual original AgentLoop and native canonical LlmRuntime/LLMService consumers: four context actions crossed with baseline/token/reasoning/both configuration. Both complete serialized GenerateOptions and every durable runtime-context snapshot compare all fields/values. Only opaque message ids are mapped bijectively across the whole row; tool/call ids and all other fields remain exact. Signal facade compares actual platform/native AbortSignal instance, aborted state and shared-with-first ownership. Source stream wrapper only observes before delegating to the unchanged original MockAdapter stream. Source config objects correspond to declared native AgentOptions; no Source criteria or algorithm change. This scope does not qualify all signal/cancellation/reentry behavior, arbitrary model/provider/middleware or canonical profiles. Native imported module closure and exact selected/extracted Python3.8.10 are mandatory; Source guards are static, not complete dynamic import closure. Frozen full-gate inputs bind wider bundle metadata. Complete B3/C2 and realWin7 remain open.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
