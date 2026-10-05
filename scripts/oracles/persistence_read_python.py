import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def assets(root):
    paths = [root / 'dsh/session/bin/sqlite3.dll', root / 'dsh/session/bin/sqlite3.json']
    for directory in ('dsh/session/bin/zstd', 'dsh/session/resources/sql'):
        paths.extend(path for path in sorted((root / directory).iterdir()) if path.is_file())
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    workspace = output.with_suffix('.workspace')
    if output.exists() or workspace.exists():
        raise ValueError('Fresh persistence read output required')
    workspace.mkdir()
    reports = []
    for name in ('public', 'order'):
        path = workspace / (name + '.json')
        completed = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve().with_name('persistence_' + name + '_python.py')),
            '--root', str(root), '--output', str(path)], capture_output=True, timeout=30)
        (workspace / (name + '.log')).write_bytes(completed.stdout + completed.stderr)
        if completed.returncode or completed.stderr:
            raise RuntimeError('Actual persistence observer failed: ' + name)
        report = json.loads(path.read_text(encoding='utf-8'))
        if Path(report['root']).resolve() != root or report['executable'] != sys.executable or report['python'] != sys.version:
            raise ValueError('Actual persistence observer identity differs')
        reports.append(report)
    modules = reports[0]['modules'].copy()
    for name, expected in reports[1]['modules'].items():
        if name in modules and modules[name] != expected:
            raise ValueError('Actual imported persistence bytes changed')
        modules[name] = expected
    with output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), python=sys.version, executable=sys.executable, modules=modules,
            assets=assets(root), rows=reports[0]['rows'] + reports[1]['rows']), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
