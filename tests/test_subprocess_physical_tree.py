from pathlib import Path
import sys

import pytest

from scripts.oracles.subprocess_tree_python import NAMES, observe
from scripts.subprocess_tree_oracle import validate_observations


@pytest.fixture(scope='module')
def actual_trees():
    if sys.platform != 'win32':
        pytest.skip('Physical Windows tree observer')
    root = Path(__file__).resolve().parents[1]
    rows = observe(root, sys.executable)
    validate_observations(rows, root)
    return {row['name']: row for row in rows}


@pytest.mark.parametrize('name', NAMES)
def test_actual_owned_root_and_descendant_exit(actual_trees, name):
    observed = actual_trees[name]['observed']
    assert observed['before'] == {'root': True, 'descendant': True}
    assert observed['after'] == {'root': False, 'descendant': False}
    assert observed['exitCode'] == (23 if name == 'direct' else 0)
