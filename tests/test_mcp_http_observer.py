import copy

import pytest

from scripts.mcp_http_oracle import EXPECTED, validate_observations, validate_runtime_report


def report(tmp_path):
    return {'observations': copy.deepcopy(EXPECTED['observations']), 'consumer': {
        'registered': True, 'output': 'controlled consumer', 'retired': True, 'closed': True,
        'writers': 0, 'tasks': 0, 'pending': 0, 'childExited': True}, 'python': '3.8.10 controlled fixture',
        'root': str(tmp_path), 'module': str(tmp_path / 'dsh/__init__.py')}


def test_complete_http_specification_and_owned_consumer_are_valid(tmp_path):
    validate_runtime_report(report(tmp_path))


@pytest.mark.parametrize('index', range(16))
@pytest.mark.parametrize('damage', ['closed', 'reaped', 'header', 'packet', 'duplicate', 'missing'])
def test_each_http_raw_row_is_required_without_damage_or_duplicates(tmp_path, index, damage):
    rows = report(tmp_path)['observations']
    if damage in ('closed', 'reaped'):
        rows[index][damage] = 1
    elif damage == 'header':
        rows[index]['frames'][0]['headers']['accept'] = '*/*'
    elif damage == 'packet':
        rows[index]['frames'][0]['packet']['params']['clientInfo']['version'] = 'foreign'
    elif damage == 'duplicate':
        rows.insert(index, copy.deepcopy(rows[index]))
    else:
        rows.pop(index)
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('damage', ['version', 'empty-version', 'foreign-module', 'registered',
    'retired', 'closed', 'writers', 'tasks', 'pending', 'childExited', 'output'])
def test_http_runtime_and_consumer_provenance_cannot_be_forged(tmp_path, damage):
    value = report(tmp_path)
    if damage == 'version':
        value['python'] = '3.8.100 controlled fixture'
    elif damage == 'empty-version':
        value['python'] = ''
    elif damage == 'foreign-module':
        value['module'] = str(tmp_path / 'foreign/__init__.py')
    elif damage == 'output':
        value['consumer']['output'] = 'invented success'
    else:
        value['consumer'][damage] = False if damage in ('writers', 'tasks', 'pending') else 1
    with pytest.raises(ValueError):
        validate_runtime_report(value)
