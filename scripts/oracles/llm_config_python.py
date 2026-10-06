import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[2]
GROUPS = ('query', 'nullable')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    names = json.loads((SCRIPT_ROOT / 'scripts/oracles/llm-config-fixtures.json').read_text(encoding='utf-8'))['names']
    if output.exists():
        raise ValueError('Fresh LLM config output required')
    rows, modules, groups = [], {}, {}
    for group in GROUPS:
        child_output = output.with_suffix('.' + group + '.native.json')
        child_log = output.with_suffix('.' + group + '.log')
        if child_output.exists() or child_log.exists():
            raise ValueError('Fresh LLM config child outputs required')
        observer = SCRIPT_ROOT / ('scripts/oracles/llm_config_' + group + '_python.py')
        with child_log.open('xb') as stream:
            completed = subprocess.run([sys.executable, '-I', str(observer), '--root', str(root),
                '--output', str(child_output)], cwd=str(SCRIPT_ROOT), stdout=stream,
                stderr=subprocess.STDOUT, timeout=180)
        if completed.returncode:
            raise RuntimeError('Actual LLM config ' + group + ' observer failed; partial child diagnostics retained')
        child = json.loads(child_output.read_text(encoding='utf-8'))
        if Path(child['root']).resolve() != root or Path(child['executable']).resolve() != Path(sys.executable).resolve():
            raise ValueError('LLM config child selected root or executable differs')
        if not child['python'].startswith('3.8.10 ') or [row['name'] for row in child['rows']] != names[group]:
            raise ValueError('LLM config child version or complete rows differ')
        for name, expected in child['modules'].items():
            selected = (root / name).resolve()
            if selected.relative_to(root).as_posix() != name or not name.startswith('dsh/'):
                raise ValueError('LLM config child imported path invalid')
            if hashlib.sha256(selected.read_bytes()).hexdigest() != expected or name in modules and modules[name] != expected:
                raise ValueError('LLM config child actual imported bytes differ')
            modules[name] = expected
        groups[group] = child
        rows.extend(dict(row, group=group, name=group + '/' + row['name']) for row in child['rows'])
    with output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version,
            modules=modules, groups=groups, rows=rows), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
