"""Controller-owned review history. Matching requests arbitration, never grants PASS."""
import hashlib
import json
import re
from difflib import SequenceMatcher


def continuation_context(feedback, phase, head, archive):
    """A current work order plus compact evidence; originals remain addressable."""
    if not feedback:
        return {}
    verification = feedback.get('verification', {})
    review = feedback.get('integration_review') or feedback.get('review') or {}
    issues = [i for i in review.get('issues', []) if i.get('state', 'open') == 'open']
    repair = feedback.get('integration_repair', {})
    if repair.get('status') == 'ESCALATE':
        decided = feedback.get('contract_decision', {}).get('verdict') not in (None, 'BLOCKED')
        mode = 'IMPLEMENT_DECIDED_CONTRACT' if decided else 'CONTRACT_AMBIGUITY'
        blockers = repair.get('issues', [])
    elif (verification.get('failure_kind') == 'RESULT_PROTOCOL' or
          (verification.get('check') == 'test_paths' and verification.get('exit_code') is None)):
        mode, blockers = 'RESULT_PROTOCOL', [verification]
    elif issues:
        mode, blockers = 'CONTRACT_REPAIR', issues
    elif feedback.get('integration_test_exit_code') not in (None, 0, 1):
        mode, blockers = 'ENVIRONMENT_DIAGNOSIS', feedback.get('failed_integration_cases', [])
    elif feedback.get('failed_integration_cases'):
        mode, blockers = 'TEST_FAILURE_DIAGNOSIS', feedback['failed_integration_cases']
    else:
        mode, blockers = 'AFFECTED_CONTRACT_VERIFICATION', []
    view = {k: v for k, v in feedback.items()
            if k not in ('integration_attempt', 'contracts', 'migration', 'full_suite_failure')}
    for key in ('review', 'integration_review', 'integration_repair', 'revalidation_review'):
        if isinstance(view.get(key), dict):
            report = dict(view[key])
            report['summary'] = report.get('summary', '')[:1600]
            view[key] = report
    view['current_work'] = {
        'phase': phase, 'candidate_head': head, 'mode': mode, 'blockers': blockers,
        'original_evidence': str(archive),
        'rule': 'Fix the current blockers and their complete invariant/consumer closure. '
                'Reuse unaffected verified clauses. Old failure logs are historical evidence, '
                'not a fresh failure on this head. Consult the archived fields only as needed. '
                'A test failure needs diagnosis; retries never erase failure evidence.'}
    return {'current_work': view.pop('current_work'), **view}


def identity(issue):
    value = issue['id'].lower().replace('\\', '/')
    value = re.sub(r'^reference/', '', value)
    match = re.match(r'^(.*?\.(?:ts|tsx|js|py))(.*)$', value)
    if match:
        path, case = match.groups()
        case = re.sub(r'^[:\d,\-]+', '', case).lstrip('#:')
    else:
        path, _, case = value.partition('#')
    return path, re.sub(r'[^a-z0-9]+', '', case)


def same_issue(left, right):
    if left['id'] == right['id']:
        return True
    a, b = identity(left), identity(right)
    if a[0] != b[0]:
        return False
    if a[1] and b[1] and SequenceMatcher(None, a[1], b[1]).ratio() >= 0.65:
        return True
    def case_words(issue):
        suffix = re.split(r'\.(?:tsx?|js|py)', issue['id'].lower())[-1]
        return {w.rstrip('s') for w in re.findall(r'[a-z]{4,}', suffix)
                if w not in ('semantics', 'behavior', 'parity', 'test', 'case')}
    x, y = case_words(left), case_words(right)
    if len(x & y) >= 2 and len(x & y) / max(1, len(x | y)) >= 0.5:
        return True
    # Handles renamed invariants without assuming every issue in a file is equal.
    words = lambda i: set(re.findall(r'[a-z]{4,}', i.get('detail', '').lower()))
    x, y = words(left), words(right)
    return len(x & y) >= 6 and len(x & y) / max(1, len(x | y)) >= 0.3


def update_ledger(previous, review, round_number):
    ledger = json.loads(json.dumps(previous.get('issue_ledger', [])))
    if not ledger:
        for issue in previous.get('review', {}).get('issues', []):
            ledger.append({'key': 'finding-' + hashlib.sha256(issue['id'].encode('utf-8')).hexdigest()[:12],
                           'issue': issue, 'aliases': [issue['id']],
                           'observations': [{'round': max(0, round_number - 1), 'state': issue.get('state', 'open')}]})
    repeated = []
    for issue in review.get('issues', []):
        entry = next((e for e in ledger if issue['id'] == e['key'] or issue['id'] in e['aliases'] or same_issue(issue, e['issue'])), None)
        state = issue.get('state', 'open')
        if entry is None:
            entry = {'key': 'finding-' + hashlib.sha256(issue['id'].encode('utf-8')).hexdigest()[:12],
                     'issue': issue, 'aliases': [], 'observations': []}
            ledger.append(entry)
        elif state == 'open' and any(o['round'] < round_number for o in entry['observations']):
            repeated.append(entry['key'])
        if issue['id'] not in entry['aliases']:
            entry['aliases'].append(issue['id'])
        entry['issue'] = dict(issue, id=entry['issue']['id']) if issue['id'] == entry['key'] else issue
        observation = {'round': round_number, 'state': state}
        if observation not in entry['observations']:
            entry['observations'].append(observation)
    return ledger, sorted(set(repeated))


def review_context(previous, affected_paths, base_head=None):
    """Only prior review/decisions and controller-observed paths, never migrator claims."""
    return {'prior_review': previous.get('review'),
            'issue_ledger': previous.get('issue_ledger', []),
            'decisions': previous.get('decisions', []),
            'affected_paths': sorted(set(affected_paths)), 'base_head': base_head,
            'coverage_rule': 'Recheck every prior open finding and all previously unmapped acceptance. '
            'Reuse unaffected source-backed evidence only. Expand for changed dependencies; '
            'a prior PASS or decision is not proof on this candidate.'}
