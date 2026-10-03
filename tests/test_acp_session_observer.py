import copy

import pytest

from scripts.acp_sessions_oracle import validate_observations


def observations():
    return [
        {'mode': 'empty', 'materialized': True, 'listedIdentity': True, 'hidden': {'sessions': []},
         'closed': {}, 'listedCwd': '/workspace', 'hiddenAfterResume': {'sessions': []}},
        {'mode': 'pagination', 'pages': [{'sessions': [{'sessionId': name} for name in group]}
         for group in [['new', 'Z'], ['a', 'β'], ['😀', 'old']]]},
        {'mode': 'filter', 'result': {'sessions': [{'sessionId': 'valid-a'}, {'sessionId': 'valid-b'}]}},
        {'mode': 'cursors', 'rejected': [True] * 10},
        {'mode': 'resume-refusals', 'rejected': [True] * 6, 'factoryCalls': 0},
        {'mode': 'reservation', 'duplicateRejected': True, 'firstRejected': True, 'retryReachedFactory': True,
         'retryRejected': True, 'factoryCalls': 1, 'hidden': {'sessions': []}},
        {'mode': 'shared-close', 'refused': True, 'agentGone': True, 'results': [{}, {}], 'userCancels': 1},
        {'mode': 'close-failure', 'reported': True, 'agentGone': True, 'listedIdentity': True},
    ]


def test_declared_observation_invariants_are_accepted():
    validate_observations(observations())


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'order', 'empty', 'materialization', 'listed',
                                  'page-order', 'filter', 'negative-count', 'negative-type', 'early-factory',
                                  'retry', 'close-duplicate', 'close-error'])
def test_observer_refuses_missing_partial_or_false_success(damage):
    rows = copy.deepcopy(observations())
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[1] = copy.deepcopy(rows[0])
    elif damage == 'order':
        rows.reverse()
    elif damage == 'empty':
        rows = []
    elif damage == 'materialization':
        rows[0]['materialized'] = False
    elif damage == 'listed':
        rows[0]['hidden']['sessions'] = [{'sessionId': 'active'}]
    elif damage == 'page-order':
        rows[1]['pages'].reverse()
    elif damage == 'filter':
        rows[2]['result']['sessions'].append({'sessionId': 'child'})
    elif damage == 'negative-count':
        rows[3]['rejected'].pop()
    elif damage == 'negative-type':
        rows[3]['rejected'][0] = 1
    elif damage == 'early-factory':
        rows[4]['factoryCalls'] = 1
    elif damage == 'retry':
        rows[5]['retryReachedFactory'] = False
    elif damage == 'close-duplicate':
        rows[6]['userCancels'] = 2
    else:
        rows[7]['reported'] = False
    with pytest.raises(ValueError):
        validate_observations(rows)
