"""Generation-scoped, lossless DeepSeek Session-log request contribution."""
import weakref
import math

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import js_to_string
from dsh.core.session.current import safe
from dsh.core.session.current_vocabulary import KNOWN_SESSION_EVENT_TYPES
from dsh.core.session.types import SessionSeq
from dsh.core.session.json import UNDEFINED


ACCEPTED_EVENT_TYPE = 'session-log-deepseek/delivery-accepted'
_FOLDS = weakref.WeakKeyDictionary()
_BLOCKED_WARNINGS = weakref.WeakKeyDictionary()


def json_bytes(value):
    try:
        return len(stringify_json(value).encode('utf-8'))
    except (TypeError, ValueError, RecursionError):
        return float('inf')


def accepted_through(session):
    previous = _FOLDS.get(session, dict(scannedEvents=0, throughSeq=-1))
    through = previous['throughSeq']
    length = session.seq
    for index in range(int(previous['scannedEvents']), int(length)):
        event = session.eventAt(index)
        if event is UNDEFINED:
            raise ValueError('session-log-deepseek: missing event %s below captured length %s' % (index, js_to_string(length)))
        if event['type'] != ACCEPTED_EVENT_TYPE:
            continue
        data, seq = event['data'], event['seq']
        version = data.get('sessionFormatVersion')
        version = 0 if version is None else version
        if not safe(version, True, True):
            raise ValueError('session-log-deepseek: malformed acceptance format version at seq ' + js_to_string(seq))
        if version != session.header.version:
            continue
        try:
            accepted = SessionSeq(data.get('throughSeq'))
        except (TypeError, ValueError):
            raise ValueError('session-log-deepseek: malformed acceptance watermark at seq ' + js_to_string(seq)) from None
        if not isinstance(data.get('sessionId'), str) or not data['sessionId'] or accepted >= seq:
            raise ValueError('session-log-deepseek: malformed acceptance watermark at seq ' + js_to_string(seq))
        if data['sessionId'] == session.id:
            through = max(through, accepted)
    _FOLDS[session] = dict(scannedEvents=length, throughSeq=through)
    return through


acceptedThrough = accepted_through


def wire_header(session):
    header = session.header
    result = dict(version=header.version, id=str(header.id), createdAt=header.createdAt)
    for key in ('cwd', 'parentSession', 'origin', 'delegationDepth', 'agentPreset'):
        value = getattr(header, key)
        if value is not None:
            result[key] = value
    if header.isSeeded:
        result['seedLength'] = session.inheritedEventCount
    return result


def wire_event(event):
    kind = event['type']
    result = {key: event[key] for key in ('type', 'seq', 'time', 'data')}
    if 'ignorable' in event:
        result['ignorable'] = event['ignorable']
    if kind in ('developer/message', 'system/message', 'user/message', 'assistant/message', 'tool/result'):
        op = event['surfaceOp']
        result['surfaceOp'] = op if op == 'append' else {key: op[key] for key in ('op', 'startSeq', 'endSeq')}
        if kind != 'assistant/message' and 'sourceEventSeqs' in event:
            result['sourceEventSeqs'] = list(event['sourceEventSeqs'])
    elif kind not in KNOWN_SESSION_EVENT_TYPES and event.get('ignorable') is True:
        for key in ('surfaceOp', 'sourceEventSeqs'):
            if key in event:
                result[key] = event[key]
    return result


class CurrentSessionLogDeepSeekService(Service):
    def __init__(self, ctx, config):
        super().__init__(ctx, 'sessionLogDeepSeek')
        self.config = config
        self.exclusions = []
        max_bytes = config['maxBytes']
        def prepare(request):
            enabled = self.config['enabled']
            if not (enabled.get() if hasattr(enabled, 'get') else enabled):
                return None
            identity = request.get('sessionId')
            session = ctx.get('sessions').get(identity) if identity is not None else None
            if session is None:
                return None
            upload = dict(sessionId=session.id)
            if 'purpose' in request:
                upload['purpose'] = request['purpose']
            for entry in list(self.exclusions):
                if entry['exclude'](upload):
                    return None
            after = accepted_through(session)
            pending = session.snapshotEvents(after + 1)
            envelope = dict(version=1, sessionFormatVersion=session.header.version,
                            session=wire_header(session), afterSeq=after)
            size = json_bytes(dict(envelope, throughSeq=0, events=[])) - 1
            events = []
            candidate_bytes = 0
            for event in pending:
                wire = wire_event(event)
                next_size = size + (1 if events else 0) + json_bytes(wire)
                candidate_bytes = next_size + len(str(event['seq']))
                if candidate_bytes > max_bytes:
                    break
                size = next_size
                events.append(wire)
            if not events:
                first = pending[0] if pending else None
                if first is not None and _BLOCKED_WARNINGS.get(session) != first['seq']:
                    _BLOCKED_WARNINGS[session] = first['seq']
                    seq = str(first['seq'])
                    if math.isfinite(candidate_bytes):
                        warning = ('session-log-deepseek: event %s of session "%s" needs a %s-byte'
                                   ' dsh_session_log field, above maxBytes %s; this session\'s upload stays at event %s'
                                   ' until maxBytes admits it') % (seq, session.id, candidate_bytes, max_bytes, seq)
                    else:
                        warning = ('session-log-deepseek: event %s of session "%s" is too large to serialize into a dsh_session_log field;'
                                   ' this session\'s upload stays at event %s') % (seq, session.id, seq)
                    ctx.logger.warn(warning)
                return None
            through = pending[len(events) - 1]['seq']
            value = dict(envelope, throughSeq=through, events=events)
            def accept():
                session.append(ACCEPTED_EVENT_TYPE, dict(sessionId=session.id,
                    sessionFormatVersion=session.header.version, throughSeq=through))
            return dict(value=value, accept=accept)
        ctx.get('deepseekLlmApiExtensions').register('dsh_session_log', dict(prepare=prepare))

    def registerExclusion(self, exclude):
        entry = dict(exclude=exclude)
        def setup():
            self.exclusions.append(entry)
            return lambda: self.exclusions.remove(entry)
        return self.ctx.effect(setup, 'sessionLogDeepSeek.registerExclusion()')


class CurrentSessionLogDeepSeekPlugin(Plugin):
    id = 'session-log-deepseek'
    inject = ['deepseekLlmApiExtensions', 'sessions']
    Config = Schema.object(dict(enabled=Schema.boolean().default(True).volatile(),
                                maxBytes=Schema.number().step(1).min(1).default(8 * 1024 * 1024)))

    def apply(self, ctx):
        CurrentSessionLogDeepSeekService(ctx, self.config)
