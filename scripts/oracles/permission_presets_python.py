import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


SCRIPTS = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    if output.exists():
        raise ValueError('Fresh Permission aggregate output required')
    groups, modules = {}, {}
    for group in ('lifecycle', 'domain'):
        child_output = output.with_suffix('.' + group + '.native.json')
        log = output.with_suffix('.' + group + '.log')
        if child_output.exists() or log.exists():
            raise ValueError('Fresh Permission child output required')
        observer = SCRIPTS / ('permission_presets_' + group + '_python.py')
        completed = subprocess.run([sys.executable, '-I', str(observer), '--root', str(root),
            '--output', str(child_output)], capture_output=True, timeout=90)
        with log.open('xb') as stream:
            stream.write(completed.stdout + completed.stderr)
        if completed.returncode or completed.stderr:
            raise RuntimeError('Actual Permission ' + group + 'child failed')
        child = json.loads(child_output.read_text(encoding='utf-8'))
        if Path(child['root']).resolve() != root or Path(child['executable']).resolve() != Path(sys.executable).resolve():
            raise ValueError('Permission child selected runtime differs')
        for name, expected in child['modules'].items():
            selected = (root / name).resolve()
            if selected.relative_to(root).as_posix() != name or not name.startswith('dsh/'):
                raise ValueError('Permission child imported path invalid')
            if hashlib.sha256(selected.read_bytes()).hexdigest() != expected or name in modules and modules[name] != expected:
                raise ValueError('Permission child imported bytes differ')
            modules[name] = expected
        groups[group] = child
    with output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version,
            modules=modules, groups=groups), stream, ensure_ascii=False, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
