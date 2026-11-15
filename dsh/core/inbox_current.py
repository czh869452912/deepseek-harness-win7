"""Durable rc.3 Inbox projection and command facade (candidate driver)."""
import math

from dsh.cordis.utils import js_to_string
from dsh.core.session.current import safe
from dsh.core.session.json import UNDEFINED


def _unique(state):
    identities = set()
    for message in state['next-turn'] + state['next-step']:
        identity = message.get('id', UNDEFINED)
        if identity in identities:
            raise ValueError('message "%s" is already pending' % js_to_string(identity))
        identities.add(identity)


def _apply(state, event):
    if event['type'] != 'agent/inbox/spliced':
        return state
    try:
        splice = event['data']
        target, start = splice['target'], splice['start']
        queue = state[target]
        count = splice.get('removedCount')
        count = 0 if count is None else count
        if (not safe(start, True) or start > len(queue) or not safe(count, True)
                or start + count > len(queue)):
            raise ValueError('invalid inbox splice')
        start, count = int(start), int(count)
        result = dict(state)
        result[target] = queue[:start] + list(splice['inserted']) + queue[start + count:]
        _unique(result)
        return result
    except Exception as error:
        raise ValueError('invalid persisted inbox splice at session seq %s' % event['seq']) from error


def _schema(state):
    if not isinstance(state, dict) or any(not isinstance(state.get(key), list)
                                         for key in ('next-turn', 'next-step')):
        raise TypeError('inbox state must contain pending-message arrays')
    return {key: state[key] for key in ('next-turn', 'next-step')}


INBOX_PROJECTION_DEFINITION = dict(
    key='inbox', stateVersion=1, stateSchema=_schema,
    init=lambda *args: {'next-turn': [], 'next-step': []}, apply=_apply,
    wire=dict(viewSchema=_schema, view=lambda state: state))
inboxProjectionDefinition = INBOX_PROJECTION_DEFINITION


def _truncate(value):
    if value is None:
        number = 0.0
    elif value is UNDEFINED:
        number = math.nan
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        text = js_to_string(value).strip()
        try:
            number = float(int(text, 0)) if text.lower().startswith(('0x', '0o', '0b')) else float(text) if text else 0.0
        except ValueError:
            number = math.nan
    return 0 if math.isnan(number) else math.trunc(number) if math.isfinite(number) else number


class ReactLoopInbox:
    def __init__(self, projections, session, dispatch):
        self.projections, self.session, self.dispatch = projections, session, dispatch
        # Services themselves are callable; only an actual reader takes this path.
        if callable(projections) and not hasattr(projections, 'register'):
            self._read_state = projections
        else:
            projections.register(INBOX_PROJECTION_DEFINITION)
            self._read_state = self._legacy_state

    def _legacy_state(self):
        state = self.projections.stateOf(self.session, 'inbox')
        if state is None:
            raise RuntimeError('agent "%s" cannot read inbox state: its projection registration is not active' % self.session.id)
        return state

    def current(self):
        return self._read_state()

    @property
    def nextTurn(self):
        return self.current()['next-turn']

    @property
    def nextStep(self):
        return self.current()['next-step']

    @property
    def hasPending(self):
        state = self.current()
        return bool(state['next-turn'] or state['next-step'])

    def clear(self):
        self.splice('next-step', 0, len(self.nextStep), [])
        self.splice('next-turn', 0, len(self.nextTurn), [])

    def claim(self, target, turn):
        claimed = self._mutate('next-step', 0, len(self.nextStep), [], False)
        if target == 'next-turn':
            claimed.extend(self._mutate('next-turn', 0, 1, [], False))
        for message in claimed:
            self.dispatch.emit('agent/inbox/claimed', dict(message=message, turn=turn))
        return claimed

    def append(self, target, message):
        self.splice(target, len(self.current()[target]), 0, [message])

    def prepend(self, target, message):
        self.splice(target, 0, 0, [message])

    def _locate(self, identity):
        state = self.current()
        for target in ('next-turn', 'next-step'):
            for index, message in enumerate(state[target]):
                if message.get('id', UNDEFINED) == identity:
                    return target, index
        return None

    def replace(self, identity, message):
        location = self._locate(identity)
        if location is None:
            return False
        self.splice(location[0], location[1], 1, [message])
        return True

    def remove(self, identity):
        location = self._locate(identity)
        if location is None:
            return False
        self.splice(location[0], location[1], 1, [])
        return True

    def splice(self, target, start, deleteCount, inserted):
        return self._mutate(target, start, deleteCount, inserted, True)

    def _mutate(self, target, start, delete_count, inserted, discard):
        state = self.current()
        queue = state[target]
        offset = _truncate(start)
        start = int(max(len(queue) + offset, 0) if offset < 0 else min(offset, len(queue)))
        count = int(min(max(_truncate(delete_count), 0), len(queue) - start))
        if count == 0 and not inserted:
            return []
        candidate = dict(state)
        candidate[target] = queue[:start] + list(inserted) + queue[start + count:]
        _unique(candidate)
        splice = dict(target=target, start=start, inserted=inserted)
        if count:
            splice['removedCount'] = count
            if discard:
                splice['outcome'] = 'canceled'
        removed = queue[start:start + count]
        event = self.session.append('agent/inbox/spliced', splice)
        if discard:
            for message in removed:
                self.dispatch.emit('agent/inbox/discarded', dict(message=message))
        for message in event['data']['inserted']:
            self.dispatch.emit('agent/inbox/inserted', dict(message=message))
        return removed
