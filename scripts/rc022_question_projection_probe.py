"""Compare current original timed-question folding and strict restore boundaries."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

FIXTURE = ROOT / 'tests/fixtures/user-questions/current-fold.json'


def observe():
    from dsh.interaction.question_projection import (USER_QUESTION_PROJECTION as definition,
        apply_user_question_event, questions_of, parse_view, is_timed_ask_user_question_schema)
    fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
    args = json.dumps(fixture['arguments'])
    def event(kind, data, seq=1):
        return dict(type=kind, seq=seq, data=data)
    header = event('request/header', dict(header=dict(tools=fixture['tools'])), 0)
    call = event('tool/call', dict(name='ask_user_question', callId='call_1', arguments=args))
    def result(value, **extra):
        return event('tool/result', dict(message=dict(toolCallId='call_1', content=[dict(type='text', text=value)]), **extra), 2)
    def reply(value, call_id='call_1'):
        return event('user/message', dict(source=dict(kind='user-question-reply', callId=call_id), content=[dict(type='text', text=value)]), 3)
    initial = definition['init']({}, 0)
    timed = apply_user_question_event(initial, header)
    opened = apply_user_question_event(timed, call)
    pending = result('{"pending":true}')
    continued = apply_user_question_event(opened, pending)
    batch = json.dumps(dict(answers=fixture['answers']))
    rows = dict(questions=questions_of(args), invalid=[questions_of(value) for value in fixture['invalidArguments']],
        schemas=[is_timed_ask_user_question_schema(tool) for tool in fixture['tools'] + [dict(name='bash', parameters=dict(properties=dict(timeout={}))), dict(name='ask_user_question', parameters={})]],
        legacy=apply_user_question_event(initial, call), opened=opened, continued=continued,
        repaired=apply_user_question_event(opened, result('unknown', error=dict(code='TOOL_OUTCOME_UNKNOWN'))),
        answered=apply_user_question_event(opened, result(batch)),
        failed=apply_user_question_event(opened, result(batch, error=dict(code='ERROR'))),
        malformed=apply_user_question_event(opened, result('{')),
        late=apply_user_question_event(continued, reply(batch)),
        late_without_batch=apply_user_question_event(continued, reply('{}')),
        ptc=apply_user_question_event(initial, event('tool/ptc-dispatch', dict(name='ask_user_question', subCallId='ptc_1', arguments=fixture['arguments'], content=[dict(type='text', text='{"pending":true}')], isError=False))),
        unrelated_same=apply_user_question_event(continued, event('turn/end', {})) is continued,
        wrong_reply_same=apply_user_question_event(continued, reply(batch, 'foreign')) is continued,
        inherited_same=definition['apply'](dict(initial, inheritedEventCount=2), call)['questions'] is initial['questions'])
    view = continued['questions']
    invalid_views = [dict(view, extra=True), dict(view, active=view['active'] * 2),
        dict(active=[dict(view['active'][0], extra=True)], settled=[]),
        dict(active=[], settled=[dict(callId='', answers=[])]),
        dict(active=[], settled=[dict(callId='x', answers=[dict(id='x', selected=[], extra=True)])])]
    rows['view_valid'] = parse_view(view)
    rows['view_invalid'] = []
    for value in invalid_views:
        try:
            parse_view(value)
        except ValueError:
            rows['view_invalid'].append(True)
        else:
            rows['view_invalid'].append(False)
    return rows


async def native():
    return observe()


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_question_projection.mts', 'Current timed and legacy schema discrimination, strict question parsing and restore, open/pending/unknown/answered/failed folds, PTC, late admission, inheritance and unchanged object identity.',
        [Path(__file__).resolve(), FIXTURE, ROOT / 'dsh/interaction/question_projection.py',
         ROOT / 'reference/packages/interaction/user-questions/src/projection.ts'])
