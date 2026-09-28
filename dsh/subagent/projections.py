"""Executable identity and timing projection contracts for durable child logs."""
from dsh.subagent.descriptor import parse_descriptor


def integer(value):
    if type(value) not in (int, float) or value < 0 or value != int(value):
        raise ValueError('expected non-negative integer')
    return value


def identity(value):
    if value is None:
        return value
    if not isinstance(value, dict) or set(value) - {'mode', 'label', 'seq'} or value.get('mode') not in ('one-shot', 'continuable'):
        raise ValueError('invalid subagent identity')
    integer(value.get('seq'))
    if ('label' in value or value['mode'] == 'continuable') and not isinstance(value.get('label'), str):
        raise ValueError('invalid subagent label')
    return value


def identity_state(value):
    if not isinstance(value, dict) or set(value) - {'identity'}:
        raise ValueError('invalid identity state')
    if 'identity' in value:
        if value['identity'] is None:
            raise ValueError('identity state cannot contain null')
        identity(value['identity'])
    return value


def fold_identity(state, event):
    if event['type'] != 'subagent/descriptor':
        return state
    try:
        descriptor = parse_descriptor(event['data'])
    except (TypeError, ValueError):
        descriptor = None
    if descriptor is None:
        return {}
    value = dict(mode=descriptor['mode'], seq=event['seq'])
    if 'label' in descriptor:
        value['label'] = descriptor['label']
    return {'identity': value}


def timing(value, state=False):
    allowed = {'settledMs', 'active'} | ({'pendingTurnStart', 'descriptorSeen'} if state else set())
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('invalid subagent timing')
    integer(value.get('settledMs'))
    if state and type(value.get('descriptorSeen')) is not bool:
        raise ValueError('invalid descriptorSeen')
    if 'active' in value:
        active = value['active']
        if not isinstance(active, dict) or set(active) != {'since', 'through'}:
            raise ValueError('invalid active interval')
        integer(active['since'])
        integer(active['through'])
    if 'pendingTurnStart' in value:
        integer(value['pendingTurnStart'])
    return value


def fold_timing(state, event):
    kind, stamp = event['type'], event['time']
    if kind == 'turn/start':
        return dict(state, **({'active': dict(since=stamp, through=stamp)} if state['descriptorSeen'] else {'pendingTurnStart': stamp}))
    if kind == 'subagent/descriptor':
        since = state.get('active', {}).get('since', state.get('pendingTurnStart'))
        return dict(descriptorSeen=True, settledMs=0, **({'active': dict(since=since, through=stamp)} if since is not None else {}))
    if kind == 'turn/end':
        if not state['descriptorSeen']:
            return {key: value for key, value in state.items() if key != 'pendingTurnStart'}
        if 'active' not in state:
            return state
        result = {key: value for key, value in state.items() if key != 'active'}
        result['settledMs'] += max(0, stamp - state['active']['since'])
        return result
    if 'active' not in state:
        return state
    return dict(state, active=dict(state['active'], through=stamp))


IDENTITY = dict(key='subagent', stateVersion=2, stateSchema=identity_state, init=lambda _: {},
                apply=fold_identity, wire=dict(viewSchema=identity, view=lambda state: state.get('identity')))
TIMING = dict(key='subagentTiming', stateVersion=2, stateSchema=lambda value: timing(value, True),
              init=lambda _: dict(descriptorSeen=False, settledMs=0), apply=fold_timing,
              wire=dict(viewSchema=timing, view=lambda state: {key: state[key] for key in ('settledMs', 'active') if key in state}))
