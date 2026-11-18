"""Retained historical agent-dependencies compatibility models; never current Source parity.

Current production successors are explicitly mapped in historical_domain_models.
"""
import copy
from pathlib import Path
import sys

import pytest

from scripts.agent_dependencies_cases import SOURCE_DAMAGES, VALUE_DAMAGES, damage_runtime, damage_source
from scripts.agent_dependencies_oracle import NAMES, complete_digest, identity, validate_runtime
from scripts.verify_portable import agent_dependencies_receipts


from historical_domain_models import historical_identity, historical_pair


ROOT = Path(__file__).resolve().parents[1]
identity = historical_identity('agent-dependencies', identity)


@pytest.fixture(scope='module')
def actual_pair():
    return historical_pair('agent-dependencies')


@pytest.mark.parametrize('name', NAMES)
def test_historical_source_native_agent_dependency_lifecycle(actual_pair, name):
    source, native = actual_pair
    selected_source = copy.deepcopy(source['rows'])
    selected_native = copy.deepcopy(native['rows'])
    for rows in (selected_source, selected_native):
        for position, row in enumerate(rows):
            if row['name'] != name:
                rows[position] = dict(name=row['name'])
    assert complete_digest(selected_native) == complete_digest(selected_source)


@pytest.mark.parametrize('damage', VALUE_DAMAGES)
def test_agent_dependencies_requires_complete_values_and_runtime(actual_pair, damage):
    source, native = actual_pair
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(damage_runtime(native, damage), ROOT, sys.executable, source, native['imports'])


@pytest.mark.parametrize('damage', SOURCE_DAMAGES)
def test_agent_dependencies_source_requires_pinned_guarded_inputs(actual_pair, damage):
    source, native = actual_pair
    altered = damage_source(source, damage)
    with pytest.raises((ValueError, KeyError)):
        identity(altered, ROOT / 'reference')
        validate_runtime(native, ROOT, sys.executable, altered, native['imports'])


def test_agent_dependencies_owned_interpreter_and_independent_imports(actual_pair, tmp_path):
    source, original = actual_pair
    native = copy.deepcopy(original)
    native['executable'] = str(ROOT / 'python.exe')
    validate_runtime(native, ROOT, ROOT / 'python.exe', source, original['imports'], check_files=False, owned_runtime=True)
    with pytest.raises(ValueError, match='imported closure'):
        validate_runtime(damage_runtime(native, 'module-hash'), ROOT, ROOT / 'python.exe', source,
                         original['imports'], check_files=False, owned_runtime=True)
    native['executable'] = str(tmp_path / 'python.exe')
    with pytest.raises(ValueError, match='belong'):
        validate_runtime(native, ROOT, tmp_path / 'python.exe', source, original['imports'], check_files=False, owned_runtime=True)


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_agent_dependencies_refuses_partial_receipts(tmp_path, side):
    arguments = [tmp_path / 'source.json' if side == 'source' else None,
                 tmp_path / 'native.json' if side == 'native' else None, tmp_path / 'output.json']
    with pytest.raises(RuntimeError, match='Both Agent dependency'):
        agent_dependencies_receipts(*arguments)
