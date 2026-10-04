import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.oracles.sqlite_format_inputs import build_inputs

MODULES = ['dsh/session/sqlite_codec.py', 'dsh/session/sqlite_source_seqs.py', 'dsh/session/sqlite_compression.py',
           'dsh/session/sqlite_json.py', 'dsh/session/zstd.py', 'dsh/cordis/json_text.py', 'dsh/cordis/utils.py']
ASSETS = ['dsh_zstd.dll', 'zstd-dictionary.bin', 'zstd.json', 'build-provenance.json', 'ZSTD-LICENSE',
          'LLVM-LICENSE.txt', 'MinGW-COPYING', 'MinGW-COPYING.MinGW-w64-runtime.txt', 'MinGW-COPYING.MinGW-w64.txt',
          'MinGW-COPYING.winpthreads.txt', 'MinGW-COPYING.winstorecompat.txt']
FRAME_NAMES = ['original-frame', 'empty-frame', 'unknown-header', 'header-truncated', 'tail-truncated',
               'checksum-damaged', 'invalid-utf8-bytes', 'utf8-bom-bytes', 'two-frames', 'trailing-garbage', 'packed-output-bound']
TAIL_NAMES = ['scan-empty', 'scan-valid', 'scan-invalid-tail', 'scan-invalid-committed', 'scan-gap-tail', 'scan-gap-committed',
              'scan-nonzero-base', 'packed-unknown-tag', 'packed-surface-refusal', 'serialized-byte-limit', 'serialized-surrogate-byte-limit']
INPUTS = MODULES + ['dsh/session/bin/zstd/' + name for name in ASSETS] + [
    'scripts/sqlite_format_oracle.py', 'scripts/build_zstd.py', 'scripts/oracles/sqlite_format_inputs.py',
    'scripts/oracles/sqlite_format_python.py', 'scripts/oracles/sqlite_format.probe.spec.ts',
    'scripts/oracles/vitest.sqlite-format-probe.config.mts', 'scripts/oracles/vitest.sqlite-format-source.config.mts',
    'reference/packages/session/session-persistence-sqlite/src/codec.ts',
    'reference/packages/session/session-persistence-sqlite/src/compression.ts',
    'reference/packages/session/session-persistence-sqlite/resources/zstd-dictionary.bin',
    'reference/packages/session/session-persistence-sqlite/tests/compression.spec.ts',
    'reference/packages/session/session-persistence-sqlite/tests/compression-unprofitable.spec.ts',
]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()


def names():
    inputs = build_inputs()
    return ([item['name'] for item in inputs['packs'] + inputs['decodes'] + inputs['varints']['encode'] + inputs['varints']['decode']]
            + ['bind-' + str(index) for index in range(len(inputs['compression']))] + FRAME_NAMES + TAIL_NAMES)


def module_hashes(root):
    return {name: hashlib.sha256((Path(root) / name).read_bytes()).hexdigest() for name in MODULES}


def asset_hashes(root):
    return {name: hashlib.sha256((Path(root) / 'dsh/session/bin/zstd' / name).read_bytes()).hexdigest() for name in ASSETS}


def observation_digest(rows):
    if not isinstance(rows, list) or [row.get('name') if isinstance(row, dict) else None for row in rows] != names():
        raise ValueError('SQLite format observation inventory differs')
    for row in rows:
        if set(row) not in ({'name', 'value'}, {'name', 'error'}):
            raise ValueError('SQLite format outcome is malformed')
        if 'error' in row and (not isinstance(row['error'], dict) or set(row['error']) != {'code', 'name', 'message'}
                              or not isinstance(row['error']['message'], str) or not isinstance(row['error']['name'], str)):
            raise ValueError('SQLite format refusal is malformed')
    return digest(rows)


def source_identity(source):
    if (not isinstance(source, dict) or set(source) != {'node', 'zstd', 'frames', 'rows'}
            or source['node'] != 'v22.22.2' or source['zstd'] != '1.5.7'):
        raise ValueError('Pinned SQLite format Source runtime differs')
    frames = source['frames']
    if not isinstance(frames, list) or [item.get('name') if isinstance(item, dict) else None for item in frames] != FRAME_NAMES:
        raise ValueError('SQLite format compressed input inventory differs')
    for item in frames:
        expected = {'name', 'hex', 'maxOutputLength'} if item['name'] == 'packed-output-bound' else {'name', 'hex'}
        if (set(item) != expected or not isinstance(item['hex'], str) or not re.fullmatch('(?:[0-9a-f]{2})*', item['hex'])
                or len(item['hex']) > 200000 or ('maxOutputLength' in item and item['maxOutputLength'] != 1048576)):
            raise ValueError('SQLite format compressed inputs are malformed')
    return observation_digest(source['rows']), digest(frames)


def validate_hashes(observed, expected, keys):
    if (not isinstance(expected, dict) or set(expected) != set(keys)
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value) for value in expected.values())
            or observed != expected):
        raise ValueError('SQLite format owned file closure differs')


def validate_runtime(report, root=None, expected_digest=None, expected_frames=None, expected_modules=None, expected_assets=None):
    fields = {'root', 'python', 'moduleFile', 'modules', 'assets', 'libraryFile', 'zstdVersion', 'frameInputsSha256', 'rows'}
    if not isinstance(report, dict) or set(report) != fields or not isinstance(report['root'], str):
        raise ValueError('SQLite format runtime receipt is incomplete')
    root = Path(root if root is not None else report['root']).resolve()
    if (report['root'] != str(root) or report['python'] != '3.8.10' or report['moduleFile'] != str(root / MODULES[0])
            or report['libraryFile'] != str(root / 'dsh/session/bin/zstd/dsh_zstd.dll') or report['zstdVersion'] != '1.5.7'):
        raise ValueError('SQLite format runtime provenance differs')
    validate_hashes(report['modules'], module_hashes(root) if expected_modules is None else expected_modules, MODULES)
    validate_hashes(report['assets'], asset_hashes(root) if expected_assets is None else expected_assets, ASSETS)
    observed = observation_digest(report['rows'])
    for value, expected, name in ((observed, expected_digest, 'observations'),
                                  (report['frameInputsSha256'], expected_frames, 'compressed inputs')):
        if (not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value)
                or expected is not None and (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected) or value != expected)):
            raise ValueError('SQLite format ' + name + ' differ from actual Source')


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
            raise ValueError('SQLite format requires the unchanged pinned Source')
        def hashes():
            return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}
        report.update(target_upstream=target, inputSha256=hashes())
        inputs_path = output.with_name(output.stem + '.inputs.json')
        inputs_path.write_text(json.dumps(build_inputs(), ensure_ascii=True) + '\n', encoding='utf-8')
        source_path, native_path = [output.with_name(output.stem + '.' + side + '.json') for side in ('source', 'native')]
        node = shutil.which('node')
        if node is None:
            raise ValueError('SQLite format requires pinned Node')
        commands = [[node, str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'), 'run', '--config',
                     str(ROOT / 'scripts/oracles/vitest.sqlite-format-probe.config.mts')],
                    [sys.executable, '-I', str(ROOT / 'scripts/oracles/sqlite_format_python.py'), str(native_path),
                     '--inputs', str(inputs_path), '--source', str(source_path)]]
        for index, command in enumerate(commands):
            result = subprocess.run(command, cwd=str(ROOT), env=dict(os.environ, SQLITE_FORMAT_INPUT=str(inputs_path),
                                    SQLITE_FORMAT_OUTPUT=str(source_path)), capture_output=True, timeout=120)
            output.with_name(output.stem + '.' + str(index) + '.log').write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise ValueError('SQLite format observer failed: ' + str(index))
        source = json.loads(source_path.read_text(encoding='utf-8'))
        native = json.loads(native_path.read_text(encoding='utf-8'))
        expected_digest, expected_frames = source_identity(source)
        validate_runtime(native, ROOT, expected_digest, expected_frames)
        if report['inputSha256'] != hashes():
            raise ValueError('SQLite format observation inputs changed')
        report.update(status='passed', cases=len(source['rows']), observationsSha256=expected_digest,
                      frameInputsSha256=expected_frames, generatedInputsSha256=hashlib.sha256(inputs_path.read_bytes()).hexdigest(),
                      scope='Bounded actual schema-19 codec/compression/provenance/physical-tail format; canonical store, complete malformed/plugin ABI and real Win7 remain unaccepted.')
    except Exception as error:
        report['failure'] = str(error)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], cases=report.get('cases'), failure=report.get('failure'))))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
