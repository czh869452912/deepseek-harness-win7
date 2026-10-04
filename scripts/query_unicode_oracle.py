import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
INPUTS = ['scripts/query_unicode_oracle.py', 'scripts/oracles/query_unicode_python.py',
          'scripts/oracles/query_unicode.probe.spec.ts', 'scripts/oracles/vitest.query-unicode-probe.config.mts',
          'dsh/session/icu_collation.py', 'dsh/session/query_engine.py', 'dsh/session/query_requests.py',
          'dsh/session/query_schema.py', 'dsh/session/sqlite_database.py', 'dsh/cordis/json_text.py',
          'scripts/build_icu.py', 'reference/packages/session-query/session-query-sqlite/src/query.ts',
          'reference/packages/session-query/session-query-sqlite/src/index.ts']
INPUTS.extend(path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'dsh/session/bin/icu').iterdir()) if path.is_file())
CURSOR_NAMES = ['nfc', 'zero-width', 'soft-hyphen', 'word-joiner', 'canonical-order']


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def validate_observations(observed):
    if not isinstance(observed, dict) or set(observed) != {'comparisons', 'fingerprints', 'cursors'}:
        raise ValueError('Unicode observations are incomplete')
    comparisons, fingerprints = observed['comparisons'], observed['fingerprints']
    if not isinstance(comparisons, list) or len(comparisons) != 1849:
        raise ValueError('Unicode comparison inventory differs')
    if any(not isinstance(row, list) or len(row) != 3 or not all(isinstance(value, str) for value in row[:2])
           or type(row[2]) is not int or row[2] not in (-1, 0, 1) for row in comparisons):
        raise ValueError('Unicode comparisons are malformed')
    for left, right in [('é', 'e\u0301'), ('ab', 'a\u200bb'), ('ab', 'a\u00adb'),
                        ('ab', 'a\u2060b'), ('a\u0315\u0300', '\u00e0\u0315')]:
        if [left, right, 0] not in comparisons:
            raise ValueError('Unicode canonical/ignorable comparison differs')
    if not isinstance(fingerprints, list) or len(fingerprints) != 180:
        raise ValueError('Unicode fingerprint inventory differs')
    if any(not isinstance(row, dict) or set(row) != {'request', 'fingerprint'}
           or not isinstance(row['request'], dict) or not isinstance(row['fingerprint'], str) for row in fingerprints):
        raise ValueError('Unicode fingerprints are malformed')
    expected = [dict(name=name, first=['alpha'], same=['beta'],
                     reversed=dict(code='SESSION_QUERY_INVALID_CURSOR', message='session-search cursor is invalid'))
                for name in CURSOR_NAMES]
    if canonical(observed['cursors']) != canonical(expected):
        raise ValueError('Actual Unicode cursor boundaries differ')


def observation_digest(observed):
    validate_observations(observed)
    return hashlib.sha256(canonical(observed).encode('ascii')).hexdigest()


def source_identity(source):
    if not isinstance(source, dict) or (source.get('node'), source.get('icu'), source.get('unicode'), source.get('cldr')) != ('v22.22.2', '78.2', '17.0', '48.0'):
        raise ValueError('Pinned Unicode source runtime differs')
    if not isinstance(source.get('locale'), str) or not source['locale']:
        raise ValueError('Pinned Unicode source locale is missing')
    observed = {name: source[name] for name in ('comparisons', 'fingerprints', 'cursors')}
    return observation_digest(observed), source['locale']


def validate_runtime(report, root=None, expected_digest=None, expected_locale=None):
    if not isinstance(report, dict) or set(report) != {'root', 'moduleFile', 'python', 'runtime', 'observations'}:
        raise ValueError('Unicode runtime receipt is incomplete')
    validate_observations(report['observations'])
    if expected_digest is not None and (not isinstance(expected_digest, str) or len(expected_digest) != 64
            or any(character not in '0123456789abcdef' for character in expected_digest)
            or observation_digest(report['observations']) != expected_digest):
        raise ValueError('Unicode observations differ from the actual source')
    if not isinstance(report['root'], str):
        raise ValueError('Unicode runtime root is malformed')
    expected_root = Path(root if root is not None else report['root']).resolve()
    manifest = json.loads((ROOT / 'dsh/session/bin/icu/icu.json').read_text(encoding='utf-8'))
    runtime = report['runtime']
    fields = {'locale', 'normalization', 'version', 'unicodeVersion', 'cldrVersion', 'manifest', 'libraries'}
    if not isinstance(runtime, dict) or set(runtime) != fields or not isinstance(runtime['locale'], str):
        raise ValueError('Unicode runtime identity is incomplete')
    if expected_locale is not None and runtime['locale'].replace('-', '_') != expected_locale.replace('-', '_'):
        raise ValueError('Unicode runtime locale differs from the actual source')
    libraries = [dict(name=name, path=str(expected_root / 'dsh/session/bin/icu' / name),
                      sha256=manifest['dll_sha256'][name]) for name in manifest['dll_sha256']]
    if (report['root'] != str(expected_root) or report['moduleFile'] != str(expected_root / 'dsh/session/icu_collation.py')
            or report['python'] != '3.8.10' or type(runtime['normalization']) is not int or runtime['normalization'] != 17
            or canonical(runtime['version']) != canonical(manifest['version'])
            or canonical(runtime['unicodeVersion']) != canonical(manifest['unicode_version'])
            or canonical(runtime['cldrVersion']) != canonical(manifest['cldr_version'])
            or canonical(runtime['manifest']) != canonical(manifest) or canonical(runtime['libraries']) != canonical(libraries)):
        raise ValueError('Unicode runtime provenance differs')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(status='failed')
    try:
        target = json.loads((ROOT / 'migration/baseline.json').read_text(encoding='utf-8'))['target_upstream']
        actual = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        dirty = subprocess.check_output(['git', '-C', str(ROOT / 'reference'), 'status', '--porcelain'], encoding='utf-8').strip()
        if target != actual or dirty:
            raise ValueError('Unicode observations require the clean pinned upstream')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        source_path, native_path = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Unicode source observer requires Node')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run',
                     '--config', str(ROOT / 'scripts/oracles/vitest.query-unicode-probe.config.mts')],
                    [sys.executable, '-I', str(ROOT / 'scripts/oracles/query_unicode_python.py'), str(native_path)]]
        for index, command in enumerate(commands):
            completed = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, QUERY_UNICODE_OUTPUT=str(source_path)),
                                       capture_output=True, timeout=90)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(completed.stdout + completed.stderr)
            if completed.returncode:
                raise ValueError('Unicode observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        if (source.get('node'), source.get('icu'), source.get('unicode'), source.get('cldr')) != ('v22.22.2', '78.2', '17.0', '48.0'):
            raise ValueError('Pinned Unicode source runtime differs')
        source_observed = {name: source[name] for name in ('comparisons', 'fingerprints', 'cursors')}
        validate_observations(source_observed)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        validate_runtime(native, ROOT)
        if source['locale'].replace('-', '_') != native['runtime']['locale'].replace('-', '_'):
            raise ValueError('Source and native default locales differ')
        if canonical(source_observed) != canonical(native['observations']):
            raise ValueError('Actual original/native Unicode observations differ')
        if report['inputSha256'] != hashes():
            raise ValueError('Unicode observation inputs changed')
        report.update(status='passed', comparisons=1849, fingerprints=180, cursors=5, cases=2034,
                      scope='Actual current-default-locale ICU/CLDR collation, exact fingerprints and five real cursor refusals. Full Unicode regex/extraction, other domain locale order and deferred Win7 remain unaccepted.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
