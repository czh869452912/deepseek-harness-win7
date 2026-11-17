"""Fresh Native inputs and immutable historical Source for parser unit tests.

These fixtures exercise the retained receipt validators. They do not execute a
current Source oracle or establish parity/release acceptance. Current Source
and extracted qualification run separately against a frozen current candidate.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from evidence_fixtures import read_member


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = 'RC3-QUALIFICATION-20261018-228CFACC.zip'


def historical_source(name):
    return read_member(ARCHIVE, 'full-gate-root.zip!/' + name + '-paired.source.json')


def synthetic_native_model(member, required, exact=False, field='modules'):
    """Typed parser input, with conspicuous placeholder hashes for new fields."""
    value = read_member(ARCHIVE, member)
    original = value[field]
    paths = set(required) if exact else set(required) | original.keys()
    value[field] = {path: original.get(path, 'a' * 64) for path in sorted(paths)}
    destination = os.environ.get('DSH_RELEASE_PYTEST_OUTPUT')
    if destination:
        path = Path(destination) / 'parser-models'; path.mkdir(parents=True, exist_ok=True)
        (path / (Path(member).name + '.model.json')).write_text(json.dumps(dict(
            kind='Synthetic receipt-parser model; never product evidence',
            archive=ARCHIVE, member=member,
            added_placeholder_imports=sorted(paths-original.keys()),
            removed_schema_fields=sorted(original.keys()-paths)), indent=2), encoding='utf-8')
    return value


def native_fixture(name, script=None, arguments=(), source=None):
    """Run the installed legacy contract provider, never a historical Native binary."""
    from scripts.rc022_office_runtime_probe import run_observer
    with tempfile.TemporaryDirectory(prefix='gg-') as folder:
        work = Path(folder)
        output = work / 'native.json'
        command = [sys.executable, '-I', str(ROOT / 'scripts/oracles' /
                   (script or name.replace('-', '_') + '_python.py')),
                   '--root', str(ROOT), '--output', str(output)]
        command += [str(value) for value in arguments]
        if name in ('subagent-model', 'unicode-carrier'):
            command = [sys.executable, '-I', str(ROOT / 'scripts/oracles' /
                       (name.replace('-', '_') + '_python.py')), str(ROOT), str(output)]
        if source is not None:
            source_path = work / 'historical-source.json'
            source_path.write_text(json.dumps(source), encoding='utf-8')
            command += ['--source', str(source_path)]
        try:
            with (work / 'native.log').open('wb') as log:
                code = run_observer(command, ROOT, dict(os.environ), log, timeout=300)
            if code:
                raise RuntimeError('Native parser fixture failed: ' + name)
            value = json.loads(output.read_text(encoding='utf-8'))
        except BaseException:
            retained = Path(tempfile.mkdtemp(prefix='gate-fixture-failed-', dir=str(ROOT / '.goose/out')))
            shutil.copytree(work, retained, dirs_exist_ok=True)
            raise
        destination = os.environ.get('DSH_RELEASE_PYTEST_OUTPUT')
        if destination:
            retained = Path(destination) / 'parser-fixtures' / name
            retained.mkdir(parents=True, exist_ok=True)
            for path in [output, work / 'native.log']:
                shutil.copyfile(path, retained / path.name)
            (retained / 'command.json').write_text(json.dumps(
                dict(command=command, exit_code=code,
                     scope='Fresh Native legacy-contract input for receipt-parser unit controls'), indent=2), encoding='utf-8')
        return value


def pair_fixture(name):
    """Build a synthetic parser model, not a new historical/source receipt.

    Original Source members remain immutable. Their public observations supply
    parser values; the synthetic model describes the freshly executed Native
    observer's hash. The all-files Source check intentionally cannot qualify this
    model against the current Source tree.
    """
    source = historical_source(name)
    if name == 'fs-values':
        # FS parser controls need the historical literal image/read schema. The
        # current tools have a different public API. Build an explicitly
        # synthetic parser model, never execute old Source or present these
        # values/placeholder module hashes as current product observations.
        from scripts.fs_values_oracle import REQUIRED_IMPORTS
        native = read_member(ARCHIVE, 'full-gate-root.zip!/fs-values-paired.native.json')
        added = sorted(REQUIRED_IMPORTS - native['imports'].keys())
        native['imports'].update({path: 'a' * 64 for path in added})
        destination = os.environ.get('DSH_RELEASE_PYTEST_OUTPUT')
        if destination:
            path = Path(destination) / 'parser-fixtures' / name
            path.mkdir(parents=True, exist_ok=True)
            (path / 'synthetic-model.json').write_text(json.dumps(dict(
                kind='Synthetic parser model only; never current product evidence',
                archive=ARCHIVE, added_placeholder_imports=added), indent=2), encoding='utf-8')
        return dict(source=source, native=native)
    native = native_fixture(name)
    derivation = dict(kind='synthetic receipt-parser unit model',
                      original_member='full-gate-root.zip!/' + name + '-paired.source.json',
                      original_archive=ARCHIVE, changes={})
    if 'fixtureSha256' in native:
        observer = ('scripts/fs_values_oracle.py' if name == 'fs-values' else
                    'scripts/oracles/' + name.replace('-', '_') + '_python.py')
        derivation['changes'][observer] = dict(original=source['inputs'][observer],
                                               synthetic=native['fixtureSha256'])
        source['inputs'][observer] = native['fixtureSha256']
    if name == 'message-values':
        cases = 'scripts/oracles/message-values-cases.json'
        derivation['changes'][cases] = dict(original=source['casesSha256'],
                                             synthetic=native['casesSha256'])
        source['casesSha256'] = source['inputs'][cases] = native['casesSha256']
    destination = os.environ.get('DSH_RELEASE_PYTEST_OUTPUT')
    if destination:
        path = Path(destination) / 'parser-fixtures' / name / 'synthetic-model.json'
        path.write_text(json.dumps(derivation, indent=2), encoding='utf-8')
    return dict(source=source, native=native)
