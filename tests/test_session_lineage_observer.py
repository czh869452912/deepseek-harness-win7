import copy
import pytest

from scripts.session_lineage_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('change', ['missing', 'extra', 'order', 'cycle-code', 'cycle-message',
    'missing-message', 'partial-root', 'partial-parent', 'descendant-order', 'deep-count', 'deep-depth',
    'lists', 'inspect', 'signal', 'cause', 'foreign-cause', 'abort-identity', 'detached'])
def test_lineage_observer_refuses_changed_contract(change):
    rows = expected()
    indexed = {row['name']: row['observed'] for row in rows}
    if change == 'missing':
        rows.pop()
    elif change == 'extra':
        rows.append(copy.deepcopy(rows[0]))
    elif change == 'order':
        rows.reverse()
    elif change == 'cycle-code':
        indexed['cycle']['error']['code'] = 'SESSION_QUERY_SESSION_NOT_FOUND'
    elif change == 'cycle-message':
        indexed['cycle']['error']['message'] = 'cycle'
    elif change == 'missing-message':
        indexed['missing']['error']['message'] = 'missing'
    elif change == 'partial-root':
        indexed['partial']['trace']['root'] = indexed['root']['trace']['root']
    elif change == 'partial-parent':
        indexed['partial']['trace']['unresolvedParentId'] = 'target'
    elif change == 'descendant-order':
        indexed['complete']['trace']['descendants'].reverse()
    elif change == 'deep-count':
        indexed['deep']['trace']['descendants']['count'] -= 1
    elif change == 'deep-depth':
        indexed['deep']['trace']['descendants']['last']['depth'] -= 1
    elif change == 'lists':
        indexed['persisted']['counters']['lists'] = 2
    elif change == 'inspect':
        indexed['persisted']['counters']['inspections'] = 1
    elif change == 'signal':
        indexed['persisted']['counters']['sameSignal'] = False
    elif change == 'cause':
        indexed['listing-failure']['error']['sameCause'] = False
    elif change == 'foreign-cause':
        indexed['foreign-rejection']['error']['sameCause'] = False
    elif change == 'abort-identity':
        indexed['list-abort']['error']['sameFailure'] = False
    elif change == 'detached':
        indexed['clone-detachment']['sourceUnchanged'] = False
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('field,value', [('root','relative'), ('module','C:/foreign/dsh/__init__.py'),
    ('python',[3,9,0]), ('python',[3,8,9]), ('observations',[])])
def test_lineage_observer_requires_exact_runtime_provenance(field, value):
    report = dict(root='C:/owned', module='C:/owned/dsh/__init__.py', python=[3,8,10], observations=expected())
    report[field] = value
    with pytest.raises(ValueError):
        validate_runtime(report)
