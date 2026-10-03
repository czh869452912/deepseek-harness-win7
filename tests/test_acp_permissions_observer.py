import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('acp_permissions_oracle', ROOT / 'scripts/acp_permissions_oracle.py')
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)


def observations(original=False):
    return [ORACLE.expected_row(mode, response, original) for mode, response in ORACLE.RESPONSES]


def test_source_defect_stays_visible_and_other_modes_require_exact_match():
    cases = ORACLE.classify(observations(True), observations())
    assert [case['status'] for case in cases].count('matched') == 10
    assert [case['mode'] for case in cases if case['status'] == 'reviewed-original-defect'] == list(ORACLE.DEFECT_MODES)
    assert cases[4]['upstream']['outcome'] == 'allowed-once' and cases[4]['python']['outcome'] == 'unavailable'


@pytest.mark.parametrize('damage', ['empty', 'duplicate', 'reorder', 'request-id', 'choices', 'no-update',
    'bad-order', 'no-audit', 'uncorrelated', 'unsafe-grant', 'invented-response', 'lost-field'])
def test_damaged_or_vacuous_permission_observations_are_rejected(damage):
    rows = copy.deepcopy(observations())
    if damage == 'empty':
        rows.clear()
    elif damage == 'duplicate':
        rows[-1] = rows[0]
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'request-id':
        rows[0]['requests'][0]['sessionId'] = 'foreign'
    elif damage == 'choices':
        rows[0]['requests'][0]['options'].reverse()
    elif damage == 'no-update':
        rows[0]['updates'].clear()
    elif damage == 'bad-order':
        rows[0]['updateBeforePermission'] = False
    elif damage == 'no-audit':
        rows[0]['audit']['types'].pop()
    elif damage == 'uncorrelated':
        rows[0]['audit']['correlated'] = False
    elif damage == 'unsafe-grant':
        rows[4]['outcome'] = rows[4]['audit']['outcome'] = 'allowed-once'
    elif damage == 'invented-response':
        rows[4]['response']['outcome']['outcome'] = 'another'
    else:
        rows[4].pop('updateBeforePermission')
    with pytest.raises((ValueError, KeyError, TypeError)):
        ORACLE.classify(observations(True), rows)


@pytest.mark.parametrize('field', ['mode', 'response', 'requests', 'updates', 'updateBeforePermission', 'audit', 'outcome'])
def test_source_defect_predicate_cannot_accept_unrelated_differences(field):
    source, native = observations(True)[4], observations()[4]
    assert ORACLE.reviewed_malformed_outcome_difference(source, native)
    source.pop(field)
    assert not ORACLE.reviewed_malformed_outcome_difference(source, native)
