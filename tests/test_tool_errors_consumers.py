"""Retained historical tool-errors compatibility models; never current Source parity.

Current production successors are explicitly mapped in historical_domain_models.
"""
import copy
from pathlib import Path
import sys

import pytest

from scripts.tool_errors_cases import SOURCE_DAMAGES, VALUE_DAMAGES, damage_runtime, damage_source
from scripts.tool_errors_oracle import NAMES, identity, validate_runtime
from scripts.verify_portable import tool_errors_receipts


from historical_domain_models import historical_identity, historical_pair


ROOT = Path(__file__).resolve().parents[1]
identity = historical_identity('tool-errors', identity)


@pytest.fixture(scope='module')
def actual_pair():
    return historical_pair('tool-errors')


@pytest.mark.parametrize('name', NAMES)
def test_historical_source_native_tool_errors_and_prompt_ownership(actual_pair, name):
    source, native = actual_pair
    assert next(row for row in native['rows'] if row['name'] == name) == next(row for row in source['rows'] if row['name'] == name)


@pytest.mark.parametrize('damage', VALUE_DAMAGES)
def test_tool_errors_requires_complete_public_results_and_runtime(actual_pair, damage):
    source, native = actual_pair
    altered = damage_runtime(native, damage)
    with pytest.raises((ValueError, KeyError)):
        validate_runtime(altered, ROOT, sys.executable, source, native['imports'])


@pytest.mark.parametrize('damage', SOURCE_DAMAGES)
def test_tool_errors_source_requires_pinned_guarded_inputs(actual_pair, damage):
    altered = damage_source(actual_pair[0], damage)
    with pytest.raises((ValueError, KeyError)):
        identity(altered, ROOT / 'reference')


def test_tool_errors_owned_interpreter_and_independent_imports(actual_pair, tmp_path):
    source, original = actual_pair
    native = copy.deepcopy(original)
    native['executable'] = str(ROOT / 'python.exe')
    validate_runtime(native, ROOT, ROOT / 'python.exe', source, original['imports'], check_files=False, owned_runtime=True)
    altered = damage_runtime(native, 'module-bytes')
    with pytest.raises(ValueError, match='imported closure'):
        validate_runtime(altered, ROOT, ROOT / 'python.exe', source, original['imports'], check_files=False, owned_runtime=True)
    native['executable'] = str(tmp_path / 'python.exe')
    with pytest.raises(ValueError, match='belong'):
        validate_runtime(native, ROOT, tmp_path / 'python.exe', source, original['imports'], check_files=False, owned_runtime=True)


@pytest.mark.parametrize('side', ('source', 'native'))
def test_portable_tool_errors_refuses_partial_receipts(tmp_path, side):
    arguments = [tmp_path / 'source.json' if side == 'source' else None,
                 tmp_path / 'native.json' if side == 'native' else None, tmp_path / 'output.json']
    with pytest.raises(RuntimeError, match='Both tool errors'):
        tool_errors_receipts(*arguments)
