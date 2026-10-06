import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'cd5ef8148158c3a752a658978873241fdf8e2bbc'
OBSERVER_INPUTS = ('scripts/sdk_profile_oracle.py', 'scripts/sdk_profile_values.py', 'scripts/oracles/sdk_profile_driver.py',
    'scripts/oracles/sdk_profile_source.mts', 'scripts/oracles/sdk_profile_python.py', 'scripts/canonical_llm_values.py',
    'scripts/sdk_profile_imports.json', 'scripts/sdk_profile_cases.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_inputs(source_root):
    source_root = Path(source_root).resolve()
    pin = subprocess.check_output(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
    dirty = subprocess.check_output(['git', '-C', str(source_root), 'status', '--porcelain'], encoding='utf-8').strip()
    if pin != SOURCE_COMMIT or dirty:
        raise ValueError('SDK Source pin differs or is dirty')
    files = subprocess.check_output(['git', '-C', str(source_root), 'ls-files', '-z'], encoding='utf-8').split('\0')
    files = [name for name in files if name]
    if 'apps/cli/src/bin.ts' not in files or 'packages/sdk/server/src/index.ts' not in files:
        raise ValueError('SDK actual Source launcher/provider inputs missing')
    result = {'reference/' + name: digest(source_root / name) for name in files}
    result.update({name: digest(ROOT / name) for name in OBSERVER_INPUTS})
    return result


def identity(source, source_root, check_files=True):
    if source.get('sourceCommit') != SOURCE_COMMIT or source.get('node') != 'v22.22.2':
        raise ValueError('SDK Source runtime differs')
    inputs = source.get('inputs')
    required = set(OBSERVER_INPUTS) | {'reference/apps/cli/src/bin.ts', 'reference/packages/sdk/server/src/index.ts'}
    if not isinstance(inputs, dict) or not required.issubset(inputs):
        raise ValueError('SDK Source input identity missing')
    for name, value in inputs.items():
        if (not isinstance(name, str) or '\\' in name or ':' in name or '..' in Path(name).parts
                or not (name.startswith('reference/') or name in OBSERVER_INPUTS)
                or not isinstance(value, str) or len(value) != 64 or any(character not in '0123456789abcdef' for character in value)):
            raise ValueError('SDK Source input identity invalid')
    if check_files and source.get('inputs') != source_inputs(source_root):
        raise ValueError('SDK Source guarded inputs differ')
    from scripts.sdk_profile_values import observations
    rows, observed_digest = observations(source['captures'], source['destinations'], 'source')
    if rows != source.get('rows'):
        raise ValueError('SDK Source rows disagree with complete captured facts')
    return observed_digest


def validate_runtime(report, root, executable, source, modules, check_files=True):
    from scripts.sdk_profile_values import SCENARIOS, OPTIONAL_CANCEL_IMPORT, observations, validate_imports
    root = Path(root).resolve()
    if Path(report['root']).resolve() != root or not report['python'].startswith('3.8.10 '):
        raise ValueError('SDK selected root or Python differs')
    if Path(report['executable']).resolve() != Path(executable).resolve():
        raise ValueError('SDK selected interpreter differs')
    if report.get('destinations') != source['destinations']:
        raise ValueError('SDK physical workspaces differ')
    if not isinstance(modules, dict) or set(modules) != set(SCENARIOS):
        raise ValueError('SDK scenario module closures differ')
    rows, actual = observations(report['captures'], report['destinations'], 'native')
    if rows != report.get('rows'):
        raise ValueError('SDK native rows disagree with complete captured facts')
    if identity(source, ROOT / 'reference', check_files=False) != actual:
        raise ValueError('Complete SDK wire/request/durable observations differ')
    if report.get('modules') != {name: report['captures'][name]['runtime']['modules'] for name in SCENARIOS}:
        raise ValueError('SDK reported closure disagrees with actual imports')
    for name in SCENARIOS:
        approved = dict(modules[name])
        if name == 'cancel':
            approved[OPTIONAL_CANCEL_IMPORT] = modules['error'][OPTIONAL_CANCEL_IMPORT]
        validate_imports(report['captures'][name], root, executable, approved, check_files=check_files)


def observe_native(source_path, root, executable, output, phase_label):
    from scripts.sdk_profile_values import SCENARIOS, observations
    root, executable, output = Path(root).resolve(), Path(executable).resolve(), Path(output).resolve()
    source = json.loads(Path(source_path).read_text(encoding='utf-8'))
    completed = subprocess.run([str(executable), '-I', str(ROOT / 'scripts/oracles/sdk_profile_driver.py'),
        '--source-root', str(ROOT / 'reference'), '--native-root', str(root), '--native-python', str(executable),
        '--source-receipt', str(source_path), '--native-label', phase_label, '--output', str(output)],
        cwd=str(output.parent), capture_output=True, timeout=600)
    output.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
    if completed.returncode or completed.stderr:
        raise RuntimeError('Actual extracted SDK profile capture failed')
    captured = json.loads(output.read_text(encoding='utf-8'))['captures']
    native_captures = {name: captured[name]['native'] for name in SCENARIOS}
    rows, observed = observations(native_captures, source['destinations'], 'native')
    native = dict(root=str(root), executable=str(executable), python=native_captures['normal']['runtime']['python'],
        destinations=source['destinations'], captures=native_captures, rows=rows,
        modules={name: native_captures[name]['runtime']['modules'] for name in SCENARIOS})
    output.with_suffix('.native.json').write_text(json.dumps(native, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return native


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference')
    parser.add_argument('--native-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    source_root, native_root = options.source_root.resolve(), options.native_root.resolve()
    output = options.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
    captured_path = output.with_suffix('.captured.json')
    if any(path.exists() for path in (output, source_path, native_path, captured_path)):
        raise ValueError('Fresh complete SDK outputs required')
    report = dict(status='runner-error')
    try:
        inputs = source_inputs(source_root)
        completed = subprocess.run([sys.executable, '-I', str(ROOT / 'scripts/oracles/sdk_profile_driver.py'),
            '--source-root', str(source_root), '--native-root', str(native_root), '--output', str(captured_path)],
            cwd=str(ROOT), capture_output=True, timeout=600)
        output.with_suffix('.capture.log').write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError('Actual SDK profile capture failed')
        if source_inputs(source_root) != inputs:
            raise ValueError('SDK guarded Source/observer inputs changed during capture')
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(native_root))
        from scripts.sdk_profile_values import SCENARIOS, observations
        captured = json.loads(captured_path.read_text(encoding='utf-8'))['captures']
        destinations = {name: str(captured_path.with_suffix('.files') / name) for name in SCENARIOS}
        source_captures = {name: captured[name]['source'] for name in SCENARIOS}
        native_captures = {name: captured[name]['native'] for name in SCENARIOS}
        source_rows, expected = observations(source_captures, destinations, 'source')
        native_rows, actual = observations(native_captures, destinations, 'native')
        modules = {name: native_captures[name]['runtime']['modules'] for name in SCENARIOS}
        if expected != actual:
            raise ValueError('Complete SDK public/durable Source observations differ')
        source = dict(sourceCommit=SOURCE_COMMIT, node='v22.22.2', inputs=inputs, destinations=destinations,
            captures=source_captures, rows=source_rows)
        native = dict(root=str(native_root), executable=sys.executable, python=sys.version, modules=modules,
            destinations=destinations, captures=native_captures, rows=native_rows)
        identity(source, source_root)
        validate_runtime(native, native_root, sys.executable, source, modules)
        for path, value in ((source_path, source), (native_path, native)):
            with path.open('x', encoding='utf-8') as stream:
                json.dump(value, stream, indent=2, ensure_ascii=False)
                stream.write('\n')
        report = dict(status='matched', scenarios=3, observationsSha256=expected,
            frame_counts={name: len(captured[name]['source']['frames']) for name in SCENARIOS},
            scope='Actual original minimal SDK normal tool/next-model, pending-stream disposal and ordinary stream failure. Strict typed identifiers and validated live clock windows preserve full wire/durable fields. Raw owned HTTP fixture errors remain retained separately; no Root/extracted/arbitrary schedule or Win7 acceptance inferred.')
    except Exception as error:
        report['error'] = str(error)
    with output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
