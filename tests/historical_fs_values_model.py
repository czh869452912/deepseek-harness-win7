"""Immutable old contract values for parser and real fixture-retention controls.

This model cannot qualify current Source or Native behavior. Actual current FS
providers are exercised separately by rc022_native_fs and tool contracts.
"""
import copy
import json
from pathlib import Path
import sys

from release_gate_fixtures import ROOT, pair_fixture, historical_source
from scripts import fs_values_oracle as oracle


def identity(source, source_root, check_files=False):
    original = historical_source('fs-values')
    if source.get('inputs') != original['inputs']:
        raise ValueError('Immutable historical Source input closure changed')
    return oracle.identity(source, source_root, check_files=False)


def validate_runtime(report, root, executable, source, modules, check_files=False, owned_runtime=False):
    identity(source, ROOT / 'reference')
    return oracle.validate_runtime(report, root, executable, source, modules,
                                   check_files=False, owned_runtime=owned_runtime)


def parser_pair(output):
    from scripts.fs_fixture_workspace import allocate, mark_ready
    pair = pair_fixture('fs-values')
    source, native = copy.deepcopy(pair['source']), copy.deepcopy(pair['native'])
    owned = allocate(output)
    (owned / 'fixture.bin').write_bytes(b'owned cleanup fixture\n')
    (owned / 'nested').mkdir()
    (owned / 'nested' / 'fixture.bin').write_bytes(b'nested owned cleanup fixture\n')
    source['fixtureWorkspace'] = native['fixtureWorkspace'] = str(owned)
    native.update(root=str(ROOT), executable=str(Path(sys.executable).resolve()))
    identity(source, ROOT / 'reference')
    validate_runtime(native, ROOT, sys.executable, source, native['imports'])
    for suffix, value in (('.source.json', source), ('.native.json', native)):
        output.with_suffix(suffix).write_text(json.dumps(value, indent=2), encoding='utf-8')
    output.write_text(json.dumps(dict(status='matched', cases=len(source['rows']),
        observationsSha256=oracle.complete_digest(source['rows']),
        scope='Synthetic retained receipt parser model; never current Source/Native evidence')),
        encoding='utf-8')
    mark_ready(output)
    return source, native
