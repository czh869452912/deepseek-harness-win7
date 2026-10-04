import copy
import pytest

from scripts.session_filters_oracle import expected,validate_observations,validate_runtime


@pytest.mark.parametrize('change',['missing','extra','order','missing-values','null-bound','bool-bound',
    'nan-bound','infinite-bound','validation-message','owned-values','nullable-values',
    'regex-injection','whitespace','bom-trim','i-case','dotted-case','dotless-case',
    'empty-documents','surface','copied-session-call','copied-event-call','cause','signal','pre-abort'])
def test_filters_observer_refuses_changed_contract(change):
    rows = expected()
    indexed = {row['name']:row['observed'] for row in rows}
    if change == 'missing':
        rows.pop()
    elif change == 'extra':
        rows.append(copy.deepcopy(rows[0]))
    elif change == 'order':
        rows.reverse()
    elif change in ('missing-values','null-bound','bool-bound','nan-bound','infinite-bound'):
        name = dict([('missing-values','sessions-missing-values'),('null-bound','sessions-null-range'),
            ('bool-bound','sessions-bool-range'),('nan-bound','sessions-nan-range'),
            ('infinite-bound','sessions-infinite-range')])[change]
        indexed[name]['error']['code'] = 'SESSION_QUERY_INVALID_REQUEST'
    elif change == 'validation-message':
        indexed['sessions-not-array']['error']['message'] = 'filters must be an array'
    elif change == 'owned-values':
        indexed['sessions-detached-values']['filters'][0]['values'][0] = 'foreign'
    elif change == 'nullable-values':
        indexed['sessions-nullable-values']['filters'][0]['values'].pop(0)
    elif change in ('regex-injection','whitespace','bom-trim','i-case','dotted-case','dotless-case'):
        name = dict([('regex-injection','text-literal'),('whitespace','text-whitespace'),
            ('bom-trim','text-bom-trim'),('i-case','text-case-i'),('dotted-case','text-case-dotted'),
            ('dotless-case','text-case-dotless')])[change]
        indexed[name]['matches'][0] = not indexed[name]['matches'][0]
    elif change == 'empty-documents':
        indexed['text-empty-documents']['error']['code'] = None
    elif change == 'surface':
        indexed['documents-surface']['documents'][0]['surface'] = 'current'
    elif change == 'copied-session-call':
        indexed['public-sessions-before-await']['records'] = []
    elif change == 'copied-event-call':
        indexed['public-events-before-await']['documents'] = []
    elif change == 'cause':
        indexed['public-sessions-failure']['error']['sameCause'] = False
    elif change == 'signal':
        indexed['public-sessions']['counters']['sameSignal'] = False
    elif change == 'pre-abort':
        indexed['public-sessions-pre-abort']['error']['sameFailure'] = False
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('field,value',[('root','relative'),('module','C:/foreign/dsh/__init__.py'),
    ('python',[3,9,0]),('python',[3,8,9]),('observations',[])])
def test_filter_observer_requires_exact_runtime_provenance(field,value):
    report = dict(root='C:/owned',module='C:/owned/dsh/__init__.py',python=[3,8,10],observations=expected())
    report[field] = value
    with pytest.raises(ValueError):
        validate_runtime(report)
