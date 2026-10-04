import copy

import pytest

from scripts.subprocess_tree_oracle import expected, validate_observations


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'reorder', 'root-live', 'child-live',
    'root-not-live-before', 'child-not-live-before', 'wrong-exit', 'bool-exit', 'stderr',
    'zero-pid', 'bool-pid', 'duplicate-pid', 'relative-cwd', 'foreign-root', 'foreign-module',
    'wrong-python', 'missing-provenance'])
def test_tree_observer_rejects_weakened_exit_or_ownership(tmp_path, damage):
    value = copy.deepcopy(expected())
    for row in value:
        row['physical'] = {'host': 100, 'root': 101, 'descendant': 102, 'cwd': str(tmp_path)}
        row['product'] = {'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py'), 'python': [3, 8, 10]}
    validate_observations(value, tmp_path)
    row = value[0]
    if damage == 'missing':
        value.pop()
    elif damage == 'duplicate':
        value[-1] = copy.deepcopy(row)
    elif damage == 'reorder':
        value.reverse()
    elif damage == 'root-live':
        row['observed']['after']['root'] = True
    elif damage == 'child-live':
        row['observed']['after']['descendant'] = True
    elif damage == 'root-not-live-before':
        row['observed']['before']['root'] = False
    elif damage == 'child-not-live-before':
        row['observed']['before']['descendant'] = False
    elif damage == 'wrong-exit':
        row['observed']['exitCode'] = 0
    elif damage == 'bool-exit':
        value[1]['observed']['exitCode'] = False
    elif damage == 'stderr':
        row['observed']['stderr'] = 'failure'
    elif damage == 'zero-pid':
        row['physical']['root'] = 0
    elif damage == 'bool-pid':
        row['physical']['root'] = True
    elif damage == 'duplicate-pid':
        row['physical']['descendant'] = row['physical']['root']
    elif damage == 'relative-cwd':
        row['physical']['cwd'] = 'relative'
    elif damage == 'foreign-root':
        row['product']['root'] = str(tmp_path / 'foreign')
    elif damage == 'foreign-module':
        row['product']['module'] = str(tmp_path / 'foreign/dsh/__init__.py')
    elif damage == 'wrong-python':
        row['product']['python'] = [3, 9, 0]
    else:
        del row['product']
    with pytest.raises(ValueError):
        validate_observations(value, tmp_path)
