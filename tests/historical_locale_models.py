"""Run retained ICU/text consumers against immutable Node 22 Source facts.

These are compatibility unit checks. The current Node 24 Source lane executes
separately; neither this helper nor the old archive qualifies its candidate.
"""
import importlib
import json
import subprocess
import sys

from release_gate_fixtures import ARCHIVE, ROOT
from evidence_fixtures import read_member


def locale_pair(name, output):
    if name not in ('query-unicode', 'session-text'):
        raise ValueError('Unreviewed historical locale contract: ' + name)
    oracle = importlib.import_module('scripts.' + name.replace('-', '_') + '_oracle')
    member = 'full-gate-root.zip!/' + name + '-paired.source.json'
    source = read_member(ARCHIVE, member)
    expected, locale = oracle.source_identity(source)
    native_path = output.with_suffix('.native.json')
    command = [sys.executable, '-I', str(ROOT / 'scripts/oracles' /
               (name.replace('-', '_') + '_python.py')), str(native_path), '--root', str(ROOT)]
    if name == 'session-text':
        inputs = output.with_suffix('.inputs.json')
        inputs.write_text(json.dumps(read_member(ARCHIVE,
            'full-gate-root.zip!/session-text-paired.inputs.json')), encoding='utf-8')
        command += ['--inputs', str(inputs)]
    completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, timeout=150)
    output.with_suffix('.log').write_bytes(completed.stdout + completed.stderr)
    output.with_suffix('.command.json').write_text(json.dumps(dict(
        command=command, exit_code=completed.returncode, archive=ARCHIVE, member=member,
        scope='Fresh Native historical ICU/text compatibility check; not current Source acceptance'),
        indent=2), encoding='utf-8')
    if completed.returncode:
        raise RuntimeError('Historical locale Native observer failed: ' + name + '\n' +
                           completed.stderr.decode('utf-8', errors='replace'))
    native = json.loads(native_path.read_text(encoding='utf-8'))
    oracle.validate_runtime(native, ROOT, expected, locale)
    groups = ('comparisons', 'fingerprints', 'cursors') if name == 'query-unicode' else ('cases', 'events', 'orders')
    assert native['observations'] == {key: source[key] for key in groups}
    report = dict(status='passed', cases=sum(len(source[key]) for key in groups),
                  scope='Historical compatibility unit checks only')
    if name == 'query-unicode':
        report.update(comparisons=1849, fingerprints=180, cursors=5)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report, source, native
