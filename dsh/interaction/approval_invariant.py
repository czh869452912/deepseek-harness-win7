"""Package-owned approval audit pairing from the pinned upstream companion."""

import json
import weakref

from dsh.cordis.plugin import Plugin
from dsh.diagnostics.invariants import registration_result
from dsh.interaction.user_approval import APPROVAL_POLICIES, OUTCOMES

PACKAGE_NAME = '@deepseek-ai/dsh-user-approval'


class _Trace:
    def __init__(self):
        self.open_turn = None
        self.pending = set()


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _validate(trace, event, fail):
    kind, data = event['type'], event['data']
    if kind == 'approval/asked':
        if trace.open_turn is None:
            fail('approval/asked appended outside any open turn')
        if not data['toolName']:
            fail('approval/asked toolName must be non-empty')
        if data['id'] in trace.pending:
            fail('approval/asked repeated open id ' + _json(data['id']))
        return 'asked', data['id']
    if kind == 'approval/decided':
        if trace.open_turn is None:
            fail('approval/decided appended outside any open turn')
        if data['id'] not in trace.pending:
            fail('approval/decided has no matching approval/asked for id ' + _json(data['id']))
        if data['outcome'] not in OUTCOMES:
            fail('approval/decided carries unknown outcome ' + _json(data['outcome']))
        return 'decided', data['id']
    if kind == 'approval/policy' and data['policy'] not in APPROVAL_POLICIES:
        fail('approval/policy carries unknown policy ' + _json(data['policy']))
    return None


def _advance(trace, transition):
    kind, identity = transition
    if kind == 'asked':
        trace.pending.add(identity)
    else:
        trace.pending.remove(identity)


def _boundary(trace, event):
    if event['type'] == 'turn/start':
        trace.open_turn = event['data']['turn']
        return True
    if event['type'] == 'turn/end':
        trace.open_turn = None
        return True
    return False


def install(ctx, fail):
    traces, staged = weakref.WeakKeyDictionary(), {}

    def seed(session):
        trace = _Trace()
        traces[session] = trace
        for event in session.events:
            _boundary(trace, event)
            transition = _validate(trace, event, fail)
            if transition is not None:
                _advance(trace, transition)
        return trace

    def trace_for(session):
        trace = traces.get(session)
        return seed(session) if trace is None else trace

    for session in ctx.get('sessions').list():
        seed(session)
    ctx.on('session/created', seed, global_listener=True)

    def published(session, event):
        trace = trace_for(session)
        if _boundary(trace, event) or event['type'] not in ('approval/asked', 'approval/decided'):
            return
        candidate = staged.pop(id(event), None)
        if candidate is None or candidate[0]() is not event or candidate[1]() is not session:
            fail('approval audit event published without pre-commit validation')
        _advance(trace, candidate[2])

    def dispatch(_mode, event_name, args, *extra):
        if event_name != 'session/event':
            return
        session, event = args[:2]
        transition = _validate(trace_for(session), event, fail)
        if transition is not None:
            identity = id(event)
            try:
                event_ref = weakref.ref(event, lambda _ref: staged.pop(identity, None))
            except TypeError:
                # Explicit emit can publish a plain dict. Native append uses
                # weak-referenceable immutable JSON candidates.
                event_ref = lambda: event
            staged[identity] = event_ref, weakref.ref(session), transition

    ctx.on('session/event', published, global_listener=True)
    ctx.on('internal/dispatch', dispatch, global_listener=True)

    def dispose():
        staged.clear()
        traces.clear()

    return dispose


install.inject = ['sessions']


class ApprovalInvariantPlugin(Plugin):
    name = 'user-approval-invariant'
    inject = ['invariants']

    def apply(self, ctx, config=None):
        return registration_result(ctx.get('invariants').register(PACKAGE_NAME, install))
