import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAMES = [origin + '-' + str(status) for origin in ('same', 'cross') for status in (301, 302, 303, 307, 308)]
NAMES += ['same-307-twenty', 'same-307-twenty-one', 'same-307-loop', 'cross-back-307', 'rewrite-then-preserve']
NAMES += ['raw-' + origin + '-POST-' + str(status) for origin in ('same', 'cross') for status in (302, 307)]
NAMES += ['raw-same-PUT-' + str(status) for status in (301, 303, 307)]
NAMES += ['raw-same-HEAD-303', 'raw-same-credentials', 'raw-cross-credentials', 'raw-unsupported-protocol',
          'raw-relative-fragment', 'raw-abort-before-follow', 'raw-stalled-redirect-body']
REQUIRED_MODULES = {'dsh/llm/http_stream.py', 'dsh/llm/llm_deepseek.py', 'dsh/llm/llm_service.py',
                    'dsh/llm/stream_bridge.py', 'dsh/cordis/context.py', 'dsh/cordis/environment.py'}


def identity(rows):
    if not isinstance(rows, list) or [row.get('name') for row in rows] != NAMES:
        raise ValueError('HTTP redirect observations incomplete or reordered')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_runtime(report, root, expected_digest, expected_modules):
    if __package__:
        from scripts.import_paths import resolve_import_path
    else:
        from import_paths import resolve_import_path
    if not isinstance(report, dict):
        raise ValueError('HTTP redirect runtime receipt missing')
    if report.get('root') != str(root.resolve()) or report.get('python') != '3.8.10':
        raise ValueError('HTTP redirect selected runtime differs')
    if identity(report.get('rows')) != expected_digest:
        raise ValueError('HTTP redirect fresh Source observations differ')
    modules = report.get('modules')
    if not isinstance(modules, dict) or not REQUIRED_MODULES.issubset(modules) or modules != expected_modules:
        raise ValueError('HTTP redirect candidate runtime module closure differs')
    missing_prefixes = {}
    for name, value in modules.items():
        if not name.startswith('dsh/') or '..' in Path(name).parts or ':' in name or '\\' in name:
            raise ValueError('HTTP redirect module path invalid')
        path = resolve_import_path(root, name, missing_prefixes)
        if path.relative_to(root.resolve()).as_posix() != name:
            raise ValueError('HTTP redirect module escaped selected root')
        if not isinstance(value, str) or len(value) != 64 or any(character not in '0123456789abcdef' for character in value):
            raise ValueError('HTTP redirect module digest invalid')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='runner-error')
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        pin = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        if pin != target or subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip():
            raise ValueError('HTTP redirect Source pin differs or is dirty')
        if subprocess.check_output(['node', '--version'], encoding='utf-8').strip() != 'v22.22.2':
            raise ValueError('HTTP redirect requires pinned Node22.22.2')
        source_path, native_path = output.with_suffix('.source.json'), output.with_suffix('.native.json')
        environment = dict(os.environ, HTTP_REDIRECT_OUTPUT=str(source_path))
        for index, command in enumerate([
            ['node', '--expose-internals', 'scripts/oracles/official/node_modules/vitest/vitest.mjs', 'run', '--config', 'scripts/oracles/vitest.http-redirect-probe.config.mts'],
            [sys.executable, 'scripts/oracles/http_redirect_python.py', '--root', str(ROOT), '--output', str(native_path)],
        ]):
            (source_path if index == 0 else native_path).unlink(missing_ok=True)
            result = subprocess.run(command, cwd=str(ROOT), env=environment, capture_output=True, timeout=45)
            output.with_suffix('.%d.log' % index).write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError('HTTP redirect observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        native = json.loads(native_path.read_text(encoding='utf-8'))
        source_digest = identity(source)
        expected_modules = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in native['modules']}
        validate_runtime(native, ROOT, source_digest, expected_modules)
        if (subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip() != target
                or subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()):
            raise ValueError('HTTP redirect Source changed during observation')
        report.update(status='matched', target_upstream=target, cases=len(source), observations_sha256=source_digest,
                      modules=native['modules'], scope='Fifteen actual DeepSeek adapter redirects and fourteen actual pinned Fetch/shared HTTP carrier boundaries; error prose, full URL/TLS/proxy/compression and other provider consumers remain unqualified.')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(report['status'])
    return 0 if report['status'] == 'matched' else 1


if __name__ == '__main__':
    raise SystemExit(main())
