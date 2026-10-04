import copy
import pytest

from scripts.session_event_trace_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('change', ['missing','extra','order','replaced-by','chain','shadowed','source-links',
    'derived-links','surface-status','surface-order','surface-cut','surface-error','surface-cause',
    'target-before-fold','window-range','window-order','window-alias','window-freeze','window-source',
    'window-priority','inspect','lists','signal','cause','foreign-cause','abort','adoption','detachment'])
def test_event_trace_observer_refuses_changed_contract(change):
    rows = expected()
    indexed = {row['name']: row['observed'] for row in rows}
    if change == 'missing':
        rows.pop()
    elif change == 'extra':
        rows.append(copy.deepcopy(rows[0]))
    elif change == 'order':
        rows.reverse()
    elif change == 'replaced-by':
        indexed['trace-original']['trace']['replacedBy'] = 4
    elif change == 'chain':
        indexed['trace-original']['trace']['replacementChain'] = [4]
    elif change == 'shadowed':
        indexed['trace-replacement']['trace']['replacedEventSeqs'] = []
    elif change == 'source-links':
        indexed['trace-replacement']['trace']['sourceEventSeqs'] = []
    elif change == 'derived-links':
        indexed['trace-original']['trace']['derivedEventSeqs'] = []
    elif change == 'surface-status':
        indexed['list-records']['records'][1]['surface'] = 'current'
    elif change == 'surface-order':
        indexed['surface-live']['surface']['events'].reverse()
    elif change == 'surface-cut':
        indexed['surface-cold']['surface']['capturedThroughSeq'] -= 1
    elif change == 'surface-error':
        indexed['surface-invalid']['error']['code'] = 'SESSION_QUERY_EVENT_NOT_FOUND'
    elif change == 'surface-cause':
        indexed['trace-invalid-surface']['error']['causeMessage'] = None
    elif change == 'target-before-fold':
        indexed['trace-missing-before-invalid']['error']['code'] = 'SESSION_QUERY_INVALID_SURFACE'
    elif change == 'window-range':
        indexed['window-clamped']['window']['endSeq'] -= 1
    elif change == 'window-order':
        indexed['window-target']['window']['events'].reverse()
    elif change == 'window-alias':
        indexed['window-alias']['targetAlias'] = False
    elif change == 'window-freeze':
        indexed['window-alias']['messageMutationRefused'] = False
    elif change == 'window-source':
        indexed['window-alias']['sourceTime'] = 99
    elif change == 'window-priority':
        indexed['window-before-abort']['error']['code'] = 'SESSION_QUERY_ABORTED'
    elif change == 'inspect':
        indexed['surface-cold']['counters']['inspections'] = 2
    elif change == 'lists':
        indexed['surface-live']['counters']['lists'] = 1
    elif change == 'signal':
        indexed['trace-inspect-failure']['counters']['sameSignal'] = False
    elif change == 'cause':
        indexed['trace-list-failure']['error']['sameCause'] = False
    elif change == 'foreign-cause':
        indexed['trace-foreign-failure']['error']['sameCause'] = False
    elif change == 'abort':
        indexed['trace-pre-abort']['error']['sameFailure'] = False
    elif change == 'adoption':
        indexed['read-session-adoption']['messageMutationRefused'] = False
    elif change == 'detachment':
        indexed['trace-detachment']['repeated']['replacementChain'].append(99)
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('field,value', [('root','relative'),('module','C:/foreign/dsh/__init__.py'),
    ('python',[3,9,0]),('python',[3,8,9]),('observations',[])])
def test_event_trace_observer_requires_exact_runtime_provenance(field,value):
    report = dict(root='C:/owned',module='C:/owned/dsh/__init__.py',python=[3,8,10],observations=expected())
    report[field] = value
    with pytest.raises(ValueError):
        validate_runtime(report)
