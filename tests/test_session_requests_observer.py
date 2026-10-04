import copy
import pytest
from scripts.session_requests_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage',['missing','extra','reordered','fields','owned-array','query-whitespace',
    'query-message','null-cursor','limit-code','bool-limit','nonfinite-limit','safe-limit','sql-injection',
    'sql-null','binding-order','sql-outer-count','matches','budget-boundary','marker','late-match',
    'emoji','snippet-whitespace','disabled-order','abort-order','provider-access','sqlite-opened'])
def test_request_observer_refuses_changed_contract(damage):
    rows = expected()
    indexed = {row['name']:row['observed'] for row in rows}
    if damage == 'missing':
        rows.pop()
    elif damage == 'extra':
        rows.append(copy.deepcopy(rows[0]))
    elif damage == 'reordered':
        rows.reverse()
    elif damage == 'fields':
        rows[0]['observed']['unknown'] = True
    elif damage == 'owned-array':
        indexed['owned-values']['value']['sessionFilters'][0]['values'][0] = 'foreign'
    elif damage == 'query-whitespace':
        indexed['non-es-whitespace']['value']['query'] = 'alpha'
    elif damage == 'query-message':
        indexed['query-not-text']['error']['message'] = 'invalid query'
    elif damage == 'null-cursor':
        indexed['cursor-null']['error']['code'] = None
    elif damage in ('limit-code','bool-limit','nonfinite-limit','safe-limit'):
        name = dict([('limit-code','limit-fraction'),('bool-limit','limit-boolean'),
            ('nonfinite-limit','limit-nan'),('safe-limit','limit-safe-overflow')])[damage]
        indexed[name]['error']['code'] = 'SESSION_QUERY_INVALID_REQUEST'
    elif damage == 'sql-injection':
        indexed['sql-injection-inert']['matches'] = ['a','b','c']
    elif damage == 'sql-null':
        indexed['nullable-duplicates']['value']['sql'] = 'cwd IN (?,?)'
    elif damage == 'binding-order':
        indexed['session-sql-owned-bindings']['value']['params'].reverse()
    elif damage == 'sql-outer-count':
        indexed['event-sql-owned-bindings']['value']['predicateCount'] = 4
    elif damage == 'matches':
        indexed['session-sql-owned-bindings']['matches'] = ['c']
    elif damage == 'budget-boundary':
        indexed['binding-budget-exact']['value'] = 'rejected'
    elif damage in ('marker','late-match','emoji','snippet-whitespace'):
        name = dict([('marker','sanitize-reserved'),('late-match','snippet-late-match-two'),
            ('emoji','snippet-emoji-codepoints'),('snippet-whitespace','snippet-es-only')])[damage]
        indexed[name]['value'] = 'foreign'
    elif damage == 'disabled-order':
        indexed['disabled-bad-query']['error']['code'] = 'SESSION_QUERY_INVALID_QUERY'
    elif damage == 'abort-order':
        indexed['invalid-query-before-abort']['error']['code'] = 'SESSION_QUERY_ABORTED'
    elif damage == 'provider-access':
        indexed['public-pre-abort']['lists'] = 1
    else:
        indexed['invalid-public-limit']['opened'] = True
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('field,value',[('root','relative'),('module','C:/foreign/dsh/__init__.py'),
    ('python',[3,9,0]),('python',[3,8,9]),('observations',[]),('unknown',True)])
def test_request_observer_requires_actual_python_runtime(field,value):
    report = dict(root='C:/owned',module='C:/owned/dsh/__init__.py',python=[3,8,10],observations=expected())
    report[field] = value
    with pytest.raises(ValueError):
        validate_runtime(report)
