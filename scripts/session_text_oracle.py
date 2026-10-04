import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.query_unicode_oracle import canonical, validate_icu_identity


DATA_SHA256 = '34f97be27ca68fdd2d3fdbb4a648c545f473c8089eafc50df792afbd8ea5650f'
INPUTS = ['scripts/session_text_oracle.py', 'scripts/oracles/session_text_inputs.py',
          'scripts/oracles/session_text_python.py', 'scripts/oracles/session_text.probe.spec.ts',
          'scripts/oracles/vitest.session-text-probe.config.mts', 'scripts/query_unicode_oracle.py',
          'dsh/session/text.py', 'dsh/session/session_query.py', 'dsh/session/tracing.py',
          'dsh/session/query_engine.py', 'dsh/session/icu_collation.py', 'dsh/session/bin/unicode/CaseFolding.txt',
          'dsh/session/bin/unicode/unicode.json',
          'tests/test_session_text.py', 'tests/test_session_text_source.py',
          'reference/packages/session-query/session-query/src/filters.ts',
          'reference/packages/session-query/session-query/src/extraction.ts',
          'reference/packages/session-query/session-query/src/corpus.ts',
          'reference/packages/session-query/session-query/src/tracing.ts',
          'reference/packages/session-query/session-query/src/index.ts',
          'reference/packages/session-query/session-query/tests/test-service.ts']
INPUTS.extend(path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'dsh/session/bin/icu').iterdir()) if path.is_file())


def validate_observations(observed):
    if not isinstance(observed, dict) or set(observed) != {'cases', 'events', 'orders'}:
        raise ValueError('Session text observations are incomplete')
    if any(not isinstance(observed[name], list) or len(observed[name]) != count
           for name, count in [('cases', 7678), ('events', 187), ('orders', 18)]):
        raise ValueError('Session text observation inventory differs')
    names = set()
    for row in observed['cases']:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or row['name'] in names:
            raise ValueError('Session text case identity differs')
        names.add(row['name'])
        if set(row) == {'name', 'matched'} and type(row['matched']) is bool:
            continue
        if set(row) != {'name', 'error'} or row['error'] != dict(code='SESSION_QUERY_INVALID_FILTER', message='session text filter must contain non-whitespace text'):
            raise ValueError('Session text case outcome differs')
    if any(not isinstance(value, str) for value in observed['events']):
        raise ValueError('Session semantic extraction is malformed')
    if observed['events'][-13:] != ['aborted', 'max-tokens', 'interrupted', '', '', '', '', '', '', '', '', 'deep', '']:
        raise ValueError('Session semantic extraction boundary differs')
    if any(not isinstance(row, dict) or set(row) != {'name', 'listed', 'children'}
           or not isinstance(row['name'], str) or not isinstance(row['listed'], list) or len(row['listed']) != 30
           or not isinstance(row['children'], list) or len(row['children']) != 29
           or not all(isinstance(value, str) for value in row['listed'] + row['children']) for row in observed['orders']):
        raise ValueError('Session corpus/lineage order inventory differs')


def observation_digest(observed):
    validate_observations(observed)
    return hashlib.sha256(canonical(observed).encode('ascii')).hexdigest()


def source_identity(source):
    if not isinstance(source, dict) or (source.get('node'), source.get('icu'), source.get('unicode'), source.get('cldr')) != ('v22.22.2', '78.2', '17.0', '48.0'):
        raise ValueError('Pinned Session text source runtime differs')
    if source.get('caseFoldingSha256') != DATA_SHA256 or not isinstance(source.get('locale'), str) or not source['locale']:
        raise ValueError('Session text source data or locale differs')
    observed = {name: source[name] for name in ('cases', 'events', 'orders')}
    return observation_digest(observed), source['locale']


def validate_runtime(report, root=None, expected_digest=None, expected_locale=None):
    if not isinstance(report, dict) or set(report) != {'root', 'moduleFile', 'python', 'unicodeDataSha256', 'runtime', 'observations'}:
        raise ValueError('Session text runtime receipt is incomplete')
    validate_observations(report['observations'])
    if not isinstance(report['root'], str):
        raise ValueError('Session text runtime root is malformed')
    expected_root = Path(root if root is not None else report['root']).resolve()
    if (report['root'] != str(expected_root) or report['moduleFile'] != str(expected_root / 'dsh/session/text.py')
            or report['python'] != '3.8.10' or report['unicodeDataSha256'] != DATA_SHA256):
        raise ValueError('Session text runtime provenance differs')
    validate_icu_identity(report['runtime'], expected_root, expected_locale)
    if expected_digest is not None and (not isinstance(expected_digest, str) or len(expected_digest) != 64
            or any(character not in '0123456789abcdef' for character in expected_digest)
            or observation_digest(report['observations']) != expected_digest):
        raise ValueError('Session text observations differ from the actual source')


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
            raise ValueError('Session text observations require the clean pinned source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        source_path, native_path, inputs_path = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native', 'inputs')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('Session text source qualification requires Node')
        commands = [[sys.executable, str(ROOT / 'scripts/oracles/session_text_inputs.py'), '--output', str(inputs_path)],
                    [node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run', '--config', str(ROOT / 'scripts/oracles/vitest.session-text-probe.config.mts')],
                    [sys.executable, '-I', str(ROOT / 'scripts/oracles/session_text_python.py'), str(native_path), '--inputs', str(inputs_path)]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, SESSION_TEXT_INPUT=str(inputs_path), SESSION_TEXT_OUTPUT=str(source_path)), capture_output=True, timeout=120)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('Session text observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        expected_digest, expected_locale = source_identity(source)
        native = json.loads(native_path.read_text(encoding='utf-8'))
        validate_runtime(native, ROOT, expected_digest, expected_locale)
        if report['inputSha256'] != hashes():
            raise ValueError('Session text observation inputs changed')
        report.update(status='passed', cases=7883, regexCases=7678, extractionCases=187, orderCases=18,
                      scope='Actual literal Unicode text matching, first-party valid extraction whitespace and current-locale corpus/lineage order. Full malformed event/plugin ABI, concurrent histories, storage schema-19, profile journeys and deferred Win7 remain unaccepted.')
    except Exception as error:
        report['error'] = str(error)
    output.write_text(json.dumps(report, ensure_ascii=True, indent=2)+'\n', encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
