import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[1]
NAMES = ('dependency-cycle', 'dispose-while-pending', 'independent-mount-0',
         'independent-mount-1', 'initial-pending-disposal', 'late-provider',
         'modified-declaration', 'dynamic-declaration-fallback')
REQUIRED_IMPORTS = {'dsh/extensions/packaged_host.py', 'dsh/extensions/cordis_guard.py',
                    'dsh/cordis/context.py', 'dsh/cordis/fiber.py'}


def observe_native(root, executable, output):
    root, executable, output = Path(root).resolve(), Path(executable).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Fresh exported Host lifecycle output required')
    completed = subprocess.run([str(executable), '-I', str(ROOT / 'scripts/oracles/exported_host_lifecycle_python.py'),
        '--root', str(root), '--output', str(output)], cwd=str(output.parent), capture_output=True, timeout=90)
    output.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
    if completed.returncode or completed.stderr:
        raise RuntimeError('Actual exported Host lifecycle observer failed')
    return json.loads(output.read_text(encoding='utf-8'))


def observation_digest(report):
    rows = report.get('rows')
    if not isinstance(rows, list) or [row.get('name') for row in rows] != list(NAMES):
        raise ValueError('Complete ordered exported Host lifecycle observations required')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def validate_runtime(report, root, executable, expected, modules, fixture_sha256, check_files=True):
    root, executable = Path(root).resolve(), Path(executable).resolve()
    if (not isinstance(report, dict) or set(report) != {'root', 'python', 'executable', 'imports', 'rows', 'fixtureSha256'}
            or report.get('root') != str(root) or not report.get('python', '').startswith('3.8.10 ')
            or Path(report['executable']).resolve() != executable or executable != root / 'python.exe'):
        raise ValueError('Exported Host selected portable or owned interpreter differs')
    if report['fixtureSha256'] != fixture_sha256:
        raise ValueError('Exported Host observer bytes differ')
    if not isinstance(modules, dict) or not REQUIRED_IMPORTS.issubset(modules) or report['imports'] != modules:
        raise ValueError('Exported Host actual imported closure differs')
    for name, sha256 in modules.items():
        if (not isinstance(name, str) or not name.startswith('dsh/') or '\\' in name or ':' in name
                or '..' in PurePosixPath(name).parts or PurePosixPath(name).as_posix() != name
                or not isinstance(sha256, str) or len(sha256) != 64
                or any(character not in '0123456789abcdef' for character in sha256)):
            raise ValueError('Exported Host imported identity invalid')
        selected = (root / name).resolve()
        if selected.relative_to(root).as_posix() != name or check_files and hashlib.sha256(selected.read_bytes()).hexdigest() != sha256:
            raise ValueError('Exported Host actual imported bytes differ')
    if observation_digest(report) != expected:
        raise ValueError('Complete exported Host mount or dependency lifecycle differs')
