import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.tool_scheduler_oracle import PREFIX_NAMES, identity, validate_runtime

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def observations(tmp_path_factory):
    output = tmp_path_factory.mktemp('tool-scheduler-source') / 'paired.json'
    subprocess.run([sys.executable, str(ROOT / 'scripts/tool_scheduler_oracle.py'), '--output', str(output)],
                   cwd=str(ROOT), env=dict(os.environ), check=True, timeout=45)
    paired = json.loads(output.read_text(encoding='utf-8'))
    native = json.loads(output.with_suffix('.native.json').read_text(encoding='utf-8'))
    assert paired['status'] == 'matched' and paired['cases'] == 30
    return native, paired['observations_sha256']


def test_actual_source_parallel_caps_settings_and_factory_consumers_match(observations):
    native, source_digest = observations
    validate_runtime(native, ROOT, source_digest, native['modules'])
    for name in ('config-empty-session', 'config-boolean-max-tokens'):
        assert next(row for row in native['rows'] if row['name'] == name) == dict(
            name=name, error='ValidationError', expected=True, published=[])


def test_actual_source_in_flight_group_keeps_cap_until_exclusive_barrier(observations):
    native, source_digest = observations
    row = next(row for row in native['rows'] if row['name'] == 'model-group-snapshot')
    assert row == dict(name='model-group-snapshot', initial=[0, 1], continuation=[0, 1, 2],
                       peaks=[2, 1], started=list(range(7)), cap=1, requests=2,
                       results=['call-' + str(index) for index in range(7)])


@pytest.mark.parametrize('name', PREFIX_NAMES)
def test_actual_source_dispatch_prefix_precedes_later_preparation_and_drains_owned_work(observations, name):
    native, source_digest = observations
    validate_runtime(native, ROOT, source_digest, native['modules'])
    row = next(row for row in native['rows'] if row['name'] == name)
    custom_failure = name == 'custom-future-throw'
    aborted = name.endswith('-abort')
    expected_prefixes = ['c1'] if aborted else ['c1', 'c2'] if custom_failure else ['c1', 'c2', 'c3']
    assert row['prefixes'] == expected_prefixes
    assert row['preparations'] == [dict(callId=identity, prefixes=expected_prefixes[:index])
                                   for index, identity in enumerate(expected_prefixes)]
    assert row['held'] == dict(settled=False)
    assert row['terminal'] == (dict(message='prefix failure', sameFailure=True) if custom_failure else None)
    assert row['calls'] == (['c1', 'c2'] if custom_failure else ['c1', 'c2', 'c3'])
    assert row['result'] == (None if custom_failure else dict(concluded=False))
    assert [result['callId'] for result in row['results']] == ([] if custom_failure else row['calls'])
    if aborted:
        assert [result['code'] for result in row['results']] == [
            None if name.startswith('custom-future-') else 'ABORTED',
            'ABORTED_BEFORE_DISPATCH', 'ABORTED_BEFORE_DISPATCH']
    if name == 'canonical-body-throw':
        assert [result['isError'] for result in row['results']] == [False, True, False]


@pytest.mark.parametrize('damage', ['missing-module', 'changed-module', 'empty-closure', 'foreign-root',
                                   'foreign-python', 'missing-row', 'duplicate-row', 'changed-row'])
def test_scheduler_receipt_refuses_incomplete_or_foreign_observations(observations, damage):
    original, source_digest = observations
    native = copy.deepcopy(original)
    expected_modules = original['modules']
    if damage == 'missing-module':
        del native['modules']['dsh/core/agent_loop_settings.py']
    elif damage == 'changed-module':
        native['modules']['dsh/core/tool_calls.py'] = '0' * 64
    elif damage == 'empty-closure':
        native['modules'] = {}
        expected_modules = {}
    elif damage == 'foreign-root':
        native['root'] = str(ROOT.parent)
    elif damage == 'foreign-python':
        native['python'] = '3.9.0'
    elif damage == 'missing-row':
        native['rows'].pop()
    elif damage == 'duplicate-row':
        native['rows'][1] = copy.deepcopy(native['rows'][0])
    else:
        native['rows'][0]['value'] = 8
    with pytest.raises(ValueError):
        validate_runtime(native, ROOT, source_digest, expected_modules)


def test_scheduler_source_order_is_part_of_identity(observations):
    native, source_digest = observations
    assert identity(native['rows']) == source_digest
    with pytest.raises(ValueError):
        identity(list(reversed(native['rows'])))
