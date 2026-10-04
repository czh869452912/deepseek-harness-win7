import copy
import pytest
from scripts.session_snapshots_oracle import expected, validate_observations, validate_runtime


@pytest.mark.parametrize('damage', ['missing', 'extra', 'reorder', 'unknown', 'lazy', 'stable',
    'qualified', 'stat', 'append', 'batch', 'noop', 'detached', 'reopen', 'copy', 'abort-name',
    'abort-message', 'abort-identity', 'same-size', 'same-file', 'same-mtime', 'rewrite', 'change-time',
    'memory', 'memory-counter', 'numeric-boolean'])
def test_snapshot_observer_refuses_changed_provider_contract(damage):
    rows = expected()
    indexed = {row['name']: row['observed'] for row in rows}
    if damage == 'missing':
        rows.pop()
    elif damage == 'extra':
        rows.append(copy.deepcopy(rows[0]))
    elif damage == 'reorder':
        rows.reverse()
    elif damage == 'unknown':
        rows[0]['observed']['unknown'] = True
    elif damage == 'lazy':
        indexed['jsonl-lazy']['count'] = 1
    elif damage in ('stable', 'qualified', 'stat'):
        indexed['jsonl-stable'][{'stable': 'same', 'qualified': 'qualified', 'stat': 'statIdentity'}[damage]] = False
    elif damage == 'append':
        indexed['jsonl-append']['changed'] = False
    elif damage == 'batch':
        indexed['sqlite-append']['counterDelta'] = 2
    elif damage == 'noop':
        indexed['sqlite-noop']['same'] = False
    elif damage == 'detached':
        indexed['sqlite-detached']['createdAt'] = 999
    elif damage == 'reopen':
        indexed['jsonl-reopen']['same'] = False
    elif damage == 'copy':
        indexed['sqlite-copy']['different'] = False
    elif damage.startswith('abort-'):
        indexed['jsonl-preabort']['error'][{'abort-name': 'name', 'abort-message': 'message',
            'abort-identity': 'sameReason'}[damage]] = False
    elif damage in ('same-size', 'same-file', 'same-mtime', 'rewrite', 'change-time'):
        indexed['jsonl-restored-stat'][{'same-size': 'sameSize', 'same-file': 'sameFile',
            'same-mtime': 'sameMtime', 'rewrite': 'changedToken', 'change-time': 'changeFieldAdvanced'}[damage]] = False
    elif damage == 'memory':
        indexed['sqlite-memory']['qualified'] = False
    elif damage == 'memory-counter':
        indexed['sqlite-memory']['counterDelta'] = 2
    else:
        indexed['jsonl-stable']['same'] = 1
    with pytest.raises(ValueError):
        validate_observations(rows)


@pytest.mark.parametrize('field,value', [('root', 'relative'), ('module', 'C:/foreign/dsh/__init__.py'),
    ('python', [3, 9, 0]), ('python', [3, 8, 9]), ('observations', []), ('unknown', True)])
def test_snapshot_observer_requires_owned_runtime(field, value):
    report = dict(root='C:/owned', module='C:/owned/dsh/__init__.py', python=[3, 8, 10], observations=expected())
    report[field] = value
    with pytest.raises(ValueError):
        validate_runtime(report)
