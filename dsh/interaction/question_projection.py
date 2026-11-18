"""Current timed-question session fold and strict persisted projection."""
import json


ASK_USER_QUESTION_TOOL = 'ask_user_question'
TIMED_WAIT_PARAMETER = 'timeout'
EMPTY_VIEW = dict(active=[], settled=[])
INITIAL_FOLD = dict(timed=False, questions=EMPTY_VIEW)


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ValueError('invalid user question object')
    return value


def _string(value):
    if not isinstance(value, str):
        raise ValueError('expected question string')
    return value


def _array(value):
    if not isinstance(value, list):
        raise ValueError('expected question array')
    return value


def _option(value, loose=False):
    if loose and isinstance(value, dict):
        value = {key: value[key] for key in ('label', 'description') if key in value}
    value = _object(value, ('label',), ('description',))
    return {key: _string(item) for key, item in value.items()}


def _question(value, tool=False):
    fields = ('id', 'question', 'header', 'options', 'multi_select') if tool else ('id', 'question', 'detail', 'header', 'options', 'multiSelect')
    if tool and isinstance(value, dict):
        value = {key: value[key] for key in fields if key in value}
    value = _object(value, ('id', 'question'), fields[2:])
    result = {}
    for key, item in value.items():
        if key == 'options':
            result[key] = [_option(option, tool) for option in _array(item)]
        elif key in ('multi_select', 'multiSelect'):
            if type(item) is not bool:
                raise ValueError('expected multiSelect boolean')
            result['multiSelect'] = item
        else:
            result[key] = _string(item)
    return result


def _answer(value):
    value = _object(value, ('id', 'selected'), ('custom',))
    result = dict(id=_string(value['id']), selected=[_string(item) for item in _array(value['selected'])])
    if 'custom' in value:
        result['custom'] = _string(value['custom'])
    return result


def parse_view(value):
    value = _object(value, ('active', 'settled'))
    active, settled = [], []
    for item in _array(value['active']):
        _object(item, ('callId', 'questions', 'state'))
        if not _string(item['callId']) or item['state'] not in ('open', 'continued'):
            raise ValueError('invalid pending question')
        questions = [_question(question) for question in _array(item['questions'])]
        if not questions:
            raise ValueError('empty question batch')
        active.append(dict(callId=item['callId'], questions=questions, state=item['state']))
    if len({item['callId'] for item in active}) != len(active):
        raise ValueError('callIds must be unique')
    for item in _array(value['settled']):
        _object(item, ('callId', 'answers'))
        if not _string(item['callId']):
            raise ValueError('empty settled callId')
        settled.append(dict(callId=item['callId'], answers=[_answer(answer) for answer in _array(item['answers'])]))
    return dict(active=active, settled=settled)


def parse_state(value):
    _object(value, ('inheritedEventCount', 'timed', 'questions'))
    count = value['inheritedEventCount']
    if type(count) is not int or not 0 <= count <= 9007199254740991 or type(value['timed']) is not bool:
        raise ValueError('invalid question fold state')
    return dict(inheritedEventCount=count, timed=value['timed'], questions=parse_view(value['questions']))


def is_timed_ask_user_question_schema(tool):
    parameters = tool.get('parameters')
    return (tool.get('name') == ASK_USER_QUESTION_TOOL and isinstance(parameters, dict)
            and isinstance(parameters.get('properties'), dict) and TIMED_WAIT_PARAMETER in parameters['properties'])


def questions_of(arguments):
    try:
        value = json.loads(arguments)
        questions = [_question(item, True) for item in _array(value['questions'])]
        return questions or None
    except (ValueError, TypeError, KeyError):
        return None


def _text_json(content):
    text = next((block for block in content if block.get('type') == 'text'), None)
    try:
        return json.loads(text['text']) if text is not None else None
    except (ValueError, TypeError, KeyError):
        return None


def _pending(content):
    value = _text_json(content)
    return isinstance(value, dict) and value.get('pending') is True


def _answers(content):
    value = _text_json(content)
    try:
        return [_answer(item) for item in _array(value['answers'])]
    except (ValueError, TypeError, KeyError):
        return None


def _settle(view, call_id, answers):
    if not any(item['callId'] == call_id for item in view['active']):
        return view
    return dict(active=[item for item in view['active'] if item['callId'] != call_id],
                settled=view['settled'] + [dict(callId=call_id, answers=answers)])


def apply_user_question_event(fold, event):
    kind, data, view = event['type'], event['data'], fold['questions']
    if kind == 'request/header':
        tools = data['header'].get('tools')
        timed = isinstance(tools, list) and any(is_timed_ask_user_question_schema(tool) for tool in tools if isinstance(tool, dict))
        return fold if timed == fold['timed'] else dict(fold, timed=timed)
    if kind == 'tool/call':
        if not fold['timed'] or data['name'] != ASK_USER_QUESTION_TOOL:
            return fold
        questions = questions_of(data['arguments'])
        if questions is None:
            return fold
        call_id, state = data['callId'], 'open'
    elif kind == 'tool/ptc-dispatch':
        if data['name'] != ASK_USER_QUESTION_TOOL or data['isError'] or not _pending(data['content']):
            return fold
        questions = questions_of(json.dumps(data['arguments']))
        if questions is None:
            return fold
        call_id, state = data['subCallId'], 'continued'
    elif kind == 'tool/result':
        call_id, message = data['message']['toolCallId'], data['message']
        if not any(item['callId'] == call_id for item in view['active']):
            return fold
        if _pending(message['content']) or (data.get('error') or {}).get('code') == 'TOOL_OUTCOME_UNKNOWN':
            questions = dict(view, active=[dict(item, state='continued') if item['callId'] == call_id else item for item in view['active']])
        else:
            answers = _answers(message['content']) if 'error' not in data and message.get('isError') is not True else None
            questions = dict(view, active=[item for item in view['active'] if item['callId'] != call_id]) if answers is None else _settle(view, call_id, answers)
        return dict(fold, questions=questions)
    elif kind == 'user/message':
        source = data['source']
        if source['kind'] != 'user-question-reply':
            return fold
        answers = _answers(data['content'])
        questions = _settle(view, source['callId'], [] if answers is None else answers)
        return fold if questions is view else dict(fold, questions=questions)
    else:
        return fold
    active = [item for item in view['active'] if item['callId'] != call_id]
    return dict(fold, questions=dict(view, active=active + [dict(callId=call_id, questions=questions, state=state)]))


def fold_user_questions(events):
    state = INITIAL_FOLD
    for event in events:
        state = apply_user_question_event(state, event)
    return state['questions']


def _apply(state, event):
    return state if event['seq'] < state['inheritedEventCount'] else apply_user_question_event(state, event)


USER_QUESTION_PROJECTION = dict(key='userQuestions', stateVersion=2, stateSchema=parse_state,
    init=lambda header, count: dict(INITIAL_FOLD, inheritedEventCount=count), apply=_apply,
    wire=dict(viewSchema=parse_view, view=lambda state: state['questions']))
