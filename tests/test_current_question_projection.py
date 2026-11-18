import copy

import pytest

from scripts.rc022_question_projection_probe import observe
from dsh.interaction.question_projection import parse_state, USER_QUESTION_PROJECTION


def test_current_question_fold_lifetimes_and_restore_fences():
    rows = observe()
    assert rows['schemas'] == [True, False, False]
    assert rows['invalid'] == [None] * 7
    assert rows['view_invalid'] == [True] * 5
    assert rows['legacy']['questions'] == dict(active=[], settled=[])
    assert rows['opened']['questions']['active'][0]['state'] == 'open'
    for key in ('continued', 'repaired'):
        assert rows[key]['questions']['active'][0]['state'] == 'continued'
    assert rows['answered']['questions'] == rows['late']['questions']
    assert rows['answered']['questions']['settled'][0]['answers'][0]['custom'] == 'also docs'
    assert rows['late_without_batch']['questions']['settled'][0]['answers'] == []
    for key in ('failed', 'malformed'):
        assert rows[key]['questions'] == dict(active=[], settled=[])
    assert rows['ptc']['questions']['active'][0]['callId'] == 'ptc_1'
    assert all(rows[key] for key in ('unrelated_same', 'wrong_reply_same', 'inherited_same'))


@pytest.mark.parametrize('patch', [dict(timed=1), dict(inheritedEventCount=True), dict(inheritedEventCount=-1),
    dict(inheritedEventCount=9007199254740992), dict(extra=True), dict(questions=dict(active=[], settled=[], extra=True))])
def test_current_question_projection_rejects_corrupt_state(patch):
    state = copy.deepcopy(USER_QUESTION_PROJECTION['init']({}, 0))
    with pytest.raises(ValueError):
        parse_state(dict(state, **patch))
