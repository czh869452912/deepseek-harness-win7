"""The scoped gate cannot hide missing observers or broaden the language exception."""
import copy
import importlib.util
from pathlib import Path
import pytest

SPEC = importlib.util.spec_from_file_location('cordis_acceptance', Path(__file__).resolve().parents[1] / 'scripts/cordis_acceptance.py')
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def report():
    rows = []
    for number in range(1, 68):
        side = {'status': 'observed', 'exit_code': 0, 'observation': {'log': []}}
        rows.append({'case': 'C%d' % number, 'status': 'matched', 'differences': [],
                     'upstream': copy.deepcopy(side), 'python': copy.deepcopy(side)})
    rows[57]['status'] = 'different'
    rows[57]['upstream']['observation'] = {'immediate': ['prefix', 'peer'], 'log': ['prefix', 'peer', 'tail']}
    rows[57]['python']['observation'] = {'immediate': ['prefix', 'tail', 'peer'], 'log': ['prefix', 'tail', 'peer']}
    return {'cases': rows}


def test_only_reviewed_language_signature_is_accepted():
    assert GATE.evaluate(report())['result'] == 'passed'


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'runner', 'unreported-difference', 'native-signature', 'adaptation'])
def test_invalid_observations_cannot_pass(mutation):
    value = report()
    rows = value['cases']
    if mutation == 'missing': rows.pop()
    elif mutation == 'duplicate': rows[-1] = rows[0]
    elif mutation == 'runner': rows[0]['python']['exit_code'] = 1
    elif mutation == 'unreported-difference': rows[0]['python']['observation'] = {'log': ['extra']}
    elif mutation == 'native-signature': rows[57]['python']['observation']['log'].append('extra')
    elif mutation == 'adaptation': rows[58]['status'] = 'different'
    assert GATE.evaluate(value)['result'] == 'failed'
