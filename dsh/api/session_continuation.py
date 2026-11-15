"""Bounded durable eligibility for an explicit empty retry prompt."""
EMPTY = dict(admitted=False, failedAttempt=False, ending=None)
CONTINUABLE_FAILURES = frozenset(('RATE_LIMIT', 'SERVER', 'TIMEOUT', 'TRANSPORT', 'EMPTY_RESPONSE', 'STREAM_CLOSED'))


def ending_schema(value):
    if value is not None and (type(value) not in (int, float) or not 0 <= value <= 9007199254740991 or value != int(value)):
        raise ValueError('continuation ending must be a non-negative integer or null')
    return value


def state_schema(value):
    if type(value.get('admitted')) is not bool or type(value.get('failedAttempt')) is not bool:
        raise ValueError('continuation flags must be booleans')
    return dict(admitted=value['admitted'], failedAttempt=value['failedAttempt'], ending=ending_schema(value['ending']))


def apply(state, event):
    kind = event['type']
    if kind == 'turn/start':
        return EMPTY
    if kind in ('step/start', 'assistant/message'):
        return dict(state, failedAttempt=False) if state['failedAttempt'] else state
    if kind == 'user/message':
        message = event['data']
        admitted = (not state['admitted'] and event.get('surfaceOp') == 'append' and
            (message['source']['kind'] == 'user' and len(message['content']) > 0 or
             message['source']['kind'] == 'retry' and len(message['content']) == 0))
        return dict(state, admitted=True) if admitted else state
    if kind == 'assistant/attempt':
        return state if state['failedAttempt'] else dict(state, failedAttempt=True)
    if kind == 'turn/end':
        reason = event['data']['reason']
        ending = event['seq'] if (reason['kind'] == 'error' and reason['error']['code'] in CONTINUABLE_FAILURES
            and state['admitted'] and state['failedAttempt']) else None
        return EMPTY if ending is None else dict(EMPTY, ending=ending)
    return state


CONTINUATION = dict(key='conversationContinuation', stateVersion=4, stateSchema=state_schema,
    init=lambda *_:EMPTY, apply=apply, wire=dict(viewSchema=ending_schema, view=lambda state:state['ending']))
