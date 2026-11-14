"""Mandatory V4 lifecycle ownership; incomplete tails keep open transactions."""
import math
import re

from dsh.core.session.json import UNDEFINED
from dsh.cordis.utils import _js_strict_equal as equal
from dsh.session.format import SessionFormatError, sessionFormatCount
from dsh.session.format_v2_to_v3.payload import display

SURFACE_TYPES = frozenset(('system/message', 'user/message', 'developer/message', 'assistant/message', 'tool/result'))
STEP_EVENT_TYPES = frozenset(('system/message', 'developer/message', 'assistant/attempt'))
RELATIONSHIP_TYPES = SURFACE_TYPES | STEP_EVENT_TYPES | frozenset((
    'turn/start', 'turn/end', 'step/start', 'step/end', 'tool/call', 'request/header', 'request/context',
    'tool/ptc-dispatch-start', 'tool/ptc-dispatch', 'llm/retry', 'llm/retry-started', 'session/title',
    'session/title-llm-request', 'command/run', 'command/done', 'compaction/start', 'compaction/summary',
    'compaction/end', 'compaction/prune', 'session/end-seed',
))


def _get(value, key):
    return value.get(key, UNDEFINED)


def _record(value, subject):
    if not isinstance(value, dict):
        raise SessionFormatError(subject + ' requires an object')
    return value


def _text(value, subject):
    if not isinstance(value, str) or not value:
        raise SessionFormatError(subject + ' requires a nonempty string')
    return value


def _array(value, subject):
    if not isinstance(value, list):
        raise SessionFormatError(subject + ' requires an array')
    return value


def _earlier(value, seq, subject):
    coordinate = sessionFormatCount(value, subject)
    if coordinate >= seq:
        raise SessionFormatError(subject + ' must name an earlier event')
    return int(coordinate)


def _index(values, value):
    return next((index for index, item in enumerate(values) if equal(item, value)), -1)


def _deep_equal(left, right):
    """Node isDeepStrictEqual restricted to lossless JSON and absent fields."""
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right and (left != 0 or math.copysign(1, left) == math.copysign(1, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_deep_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_deep_equal(a, b) for a, b in zip(left, right))
    return equal(left, right)


class Relationships:
    def __init__(self, artifact, known):
        self.artifact, self.known = artifact, known
        self.turn, self.step, self.next_turn, self.next_step = None, None, 1, 1
        self.provider, self.protected_head, self.compaction = UNDEFINED, UNDEFINED, None
        self.surface, self.tools, self.dispatches, self.retries = [], {}, {}, []
        self.started_retries, self.commands, self.orphan_compactions = set(), set(), set()
        start = UNDEFINED
        for event in artifact['events']:
            if event['type'] not in known:
                continue
            if event['type'] == 'compaction/start':
                start = event['seq']
            if event['type'] == 'compaction/end':
                start = UNDEFINED
            if event['type'] == 'session/end-seed':
                if start is not UNDEFINED:
                    self.orphan_compactions.add(start)
                start = UNDEFINED

    def require_turn(self, kind):
        if self.turn is None:
            raise SessionFormatError(kind + ' is outside an open turn')

    def require_step(self, event, data):
        if (self.turn is None or self.step is None or not equal(_get(data, 'turn'), self.turn)
                or not equal(_get(data, 'step'), self.step)):
            raise SessionFormatError(event['type'] + ' does not match an open turn and step')

    def close_tools(self, kind):
        if self.tools:
            raise SessionFormatError(kind + ' leaves unresolved tool call ' + next(iter(self.tools)))
        self.tools.clear()

    def developer(self, event, data):
        if _get(data, 'headerSeq') is UNDEFINED:
            return
        seq = _earlier(data['headerSeq'], event['seq'], 'developer/message headerSeq')
        header = self.artifact['events'][seq] if seq < len(self.artifact['events']) else None
        if header is None or header['type'] != 'request/header':
            raise SessionFormatError('developer/message headerSeq must reference an earlier request/header')
        if header['type'] not in self.known:
            raise SessionFormatError('developer/message headerSeq must reference a known request/header')
        tools = _get(_record(_get(_record(header['data'], 'request/header data'), 'header'), 'request header'), 'tools')
        content = _array(_get(_record(_get(data, 'message'), 'developer message'), 'content'), 'developer content')
        for value in content:
            if not isinstance(value, dict) or value.get('type') != 'tool-addition':
                continue
            name = _get(value, 'toolName')
            definitions = [tool for tool in tools if isinstance(tool, dict) and equal(_get(tool, 'name'), name)] if isinstance(tools, list) else []
            if len(definitions) != 1:
                raise SessionFormatError('developer/message tool-addition "{}" must name exactly one tool in headerSeq {}'.format(display(name), seq))
            definition = definitions[0]
            if not isinstance(definition.get('description'), str) or not isinstance(definition.get('parameters'), dict):
                raise SessionFormatError('developer/message tool-addition "{}" requires a complete tool definition in headerSeq {}'.format(display(name), seq))

    def fold_surface(self, event):
        kind = event['type']
        if kind not in SURFACE_TYPES:
            return
        if kind == 'system/message' and self.surface and self.protected_head is UNDEFINED:
            raise SessionFormatError('system/message requires a protected first surface head')
        if event.get('surfaceOp') == 'append':
            if kind == 'system/message' and not self.surface:
                self.protected_head = event['seq']
            self.surface.append(event['seq'])
            return
        operation = _record(_get(event, 'surfaceOp'), kind + ' surfaceOp')
        first = _index(self.surface, _earlier(_get(operation, 'startSeq'), event['seq'], 'replacement start'))
        last = _index(self.surface, _earlier(_get(operation, 'endSeq'), event['seq'], 'replacement end'))
        if first < 0 or last < first:
            raise SessionFormatError(kind + ' replacement range is not on the current surface')
        removed = self.surface[first:last + 1]
        sources = _array(_get(event, 'sourceEventSeqs'), 'replacement sourceEventSeqs')
        if any(_index(sources, seq) < 0 for seq in removed):
            raise SessionFormatError('replacement sourceEventSeqs omit a shadowed surface node')
        if self.protected_head is not UNDEFINED and _index(removed, self.protected_head) >= 0:
            if kind != 'system/message' or len(removed) != 1:
                raise SessionFormatError('surface replacement cannot shadow the protected system head')
            self.protected_head = event['seq']
        self.surface[first:last + 1] = [event['seq']]

    def tool(self, event, data):
        kind = event['type']
        if kind == 'tool/result' and event.get('surfaceOp') != 'append':
            self.require_turn(kind)
            return
        self.require_step(event, data)
        if kind == 'assistant/message':
            message = _record(_get(data, 'message'), 'assistant message')
            for value in _array(_get(message, 'content'), 'assistant content'):
                block = _record(value, 'assistant content block')
                if block.get('type') != 'tool-call':
                    continue
                identity = _text(_get(block, 'id'), 'tool call id')
                if identity in self.tools:
                    raise SessionFormatError('assistant/message repeats advertised tool call ' + identity)
                self.tools[identity] = dict(name=_get(block, 'name'), arguments=_get(block, 'arguments'), started=False)
            return
        message = _record(_get(data, 'message'), 'tool result message') if kind == 'tool/result' else None
        identity = _text(_get(data, 'callId') if message is None else _get(message, 'toolCallId'), 'tool call id')
        pending = self.tools.get(identity)
        if pending is None:
            raise SessionFormatError(kind + ' ' + identity + ' has no advertised tool lifecycle')
        if message is None:
            if pending['started'] or not equal(pending['name'], _get(data, 'name')) or not equal(pending['arguments'], _get(data, 'arguments')):
                raise SessionFormatError('tool/call ' + identity + ' does not match one advertised tool call')
            pending['started'] = True
        else:
            if not pending['started'] and not _not_started_repair(event, data, message, identity):
                raise SessionFormatError('tool/result ' + identity + ' is not the exact TOOL_NOT_STARTED repair')
            del self.tools[identity]

    def dispatch(self, event, data):
        self.require_turn(event['type'])
        identity = _text(_get(data, 'subCallId'), 'PTC subCallId')
        root = _text(_get(data, 'rootCallId'), 'PTC rootCallId')
        parent = _text(_get(data, 'parentCallId'), 'PTC parentCallId')
        existing = self.dispatches.get(identity)
        if existing is not None and not equal(_get(existing['data'], 'rootCallId'), root):
            raise SessionFormatError('PTC dispatch changes its rootCallId')
        if parent != root and not equal(_get(self.dispatches.get(parent, {}).get('data', {}), 'rootCallId'), root):
            raise SessionFormatError('PTC parentCallId does not belong to rootCallId')
        if event['type'] == 'tool/ptc-dispatch-start':
            if existing is not None:
                raise SessionFormatError('PTC dispatch repeats subCallId')
            self.dispatches[identity] = dict(data=data, settled=False)
            return
        if existing is None or existing['settled']:
            raise SessionFormatError('PTC dispatch has no unique start')
        if any(not _deep_equal(_get(existing['data'], key), _get(data, key)) for key in ('rootCallId', 'parentCallId', 'name', 'arguments')):
            raise SessionFormatError('PTC dispatch does not match its start')
        existing['settled'] = True

    def retry(self, event, data):
        identity = _text(_get(data, 'retryId'), 'retryId')
        attempt = sessionFormatCount(_get(data, 'retry'), 'retry')
        if event['type'] == 'llm/retry-started':
            scheduled = next((item for item in self.retries if equal(_get(item, 'retryId'), identity) and equal(_get(item, 'retry'), attempt)), None)
            if scheduled is None:
                raise SessionFormatError('llm/retry-started pairs no prior scheduled attempt')
            if any(not equal(_get(scheduled, key), _get(data, key)) for key in ('turn', 'step')):
                raise SessionFormatError('llm/retry-started changes scheduled coordinates')
            key = (identity, attempt)
            if key in self.started_retries:
                raise SessionFormatError('llm/retry-started repeats one scheduled attempt')
            self.started_retries.add(key)
            return
        if (self.turn is None or not equal(_get(data, 'turn'), self.turn)
                or not equal(_get(data, 'step'), self.next_step - 1 if self.step is None else self.step)):
            raise SessionFormatError('llm/retry does not match the current turn and step')
        if not equal(_get(data, 'provider'), self.provider):
            raise SessionFormatError('llm/retry provider does not match the open request/header')
        prior = next((item for item in reversed(self.retries) if all(equal(_get(item, key), _get(data, key)) for key in ('turn', 'step', 'provider', 'policyKey'))), None)
        expected = 1 if prior is None else sessionFormatCount(_get(prior, 'retry'), 'prior retry') + 1
        if not equal(attempt, expected):
            raise SessionFormatError('llm/retry skips its policy attempt sequence')
        if (any(equal(_get(item, 'retryId'), identity) for item in self.retries) if prior is None else not equal(_get(prior, 'retryId'), identity)):
            raise SessionFormatError('llm/retry must keep one retryId per policy chain')
        self.retries.append(data)

    def compact(self, event, data):
        kind = event['type']
        if kind in ('compaction/prune', 'compaction/summary'):
            self.span(event, data)
        if kind == 'compaction/prune':
            return
        if kind == 'compaction/start':
            if self.compaction is not None:
                raise SessionFormatError('compaction/start overlaps an open compaction')
            owner = None if _get(data, 'turn') is None else sessionFormatCount(_get(data, 'turn'), 'compaction turn')
            if not equal(owner, self.turn):
                raise SessionFormatError('compaction/start does not match the open turn')
            self.compaction = dict(id=_text(_get(data, 'compactionId'), 'compactionId'), command=_get(data, 'sourceCommandId'),
                                   turn=owner, seq=event['seq'], summarized=False)
            return
        current = self.compaction_owner(data, kind)
        if not equal(current['turn'], self.turn):
            raise SessionFormatError(kind + ' does not match the open turn')
        if kind == 'compaction/summary':
            if current['summarized']:
                raise SessionFormatError('compaction/summary repeats')
            current['summarized'] = True
        else:
            if not equal(_get(data, 'turn'), current['turn']):
                raise SessionFormatError('compaction/end changes its owner turn')
            if _get(data, 'error') is UNDEFINED and not current['summarized']:
                raise SessionFormatError('successful compaction/end requires one summary')
            self.compaction = None

    def compaction_owner(self, data, subject):
        current = self.compaction
        if current is None or not equal(current['id'], _get(data, 'compactionId')) or not equal(current['command'], _get(data, 'sourceCommandId')):
            raise SessionFormatError(subject + ' has no matching compaction/start')
        return current

    def span(self, event, data):
        area = _record(_get(data, 'shadowedRange'), 'compaction shadowedRange')
        start = _index(self.surface, _earlier(_get(area, 'start'), event['seq'], 'compaction range start'))
        end = _index(self.surface, _earlier(_get(area, 'end'), event['seq'], 'compaction range end'))
        seqs = _array(_get(data, 'shadowedSeqs'), 'compaction shadowedSeqs')
        if start < 0 or end < start or not _deep_equal(self.surface[start:end + 1], seqs):
            raise SessionFormatError(event['type'] + ' shadowedSeqs do not name an exact current surface span')
        if self.protected_head is not UNDEFINED and _index(seqs, self.protected_head) >= 0:
            raise SessionFormatError('compaction cannot shadow the protected system head')

    def accept(self, event):
        kind = event['type']
        if kind not in self.known or kind not in RELATIONSHIP_TYPES:
            return
        data = _record(event['data'], kind)
        if kind in STEP_EVENT_TYPES:
            self.require_step(event, data)
        if kind.startswith('turn/') and self.compaction is not None and self.compaction['seq'] not in self.orphan_compactions:
            raise SessionFormatError(kind + ' crosses an open compaction')
        self.fold_surface(event)
        if kind == 'turn/start':
            if self.turn is not None or not equal(_get(data, 'turn'), self.next_turn):
                raise SessionFormatError('turn/start does not open the expected turn')
            self.turn, self.next_step = self.next_turn, 1
            self.tools.clear()
        elif kind == 'turn/end':
            if self.turn is None or not equal(_get(data, 'turn'), self.turn) or self.step is not None:
                raise SessionFormatError('turn/end does not match the open turn with no open step')
            self.close_tools(kind)
            self.turn = None
            self.next_turn += 1
        elif kind == 'step/start':
            if self.turn is None or not equal(_get(data, 'turn'), self.turn) or self.step is not None or not equal(_get(data, 'step'), self.next_step):
                raise SessionFormatError('step/start does not match the open turn and next step')
            self.step = self.next_step
        elif kind == 'step/end':
            self.require_step(event, data)
            self.close_tools(kind)
            self.step = None
            self.next_step += 1
        elif kind in ('assistant/message', 'tool/call', 'tool/result'):
            self.tool(event, data)
        elif kind == 'developer/message':
            self.developer(event, data)
        elif kind == 'request/header':
            self.require_turn(kind)
            self.provider = _get(_record(_get(_record(_get(data, 'header'), 'request header'), 'config'), 'request config'), 'provider')
        elif kind == 'request/context':
            self.require_turn(kind)
        elif kind in ('tool/ptc-dispatch-start', 'tool/ptc-dispatch'):
            self.dispatch(event, data)
        elif kind in ('llm/retry', 'llm/retry-started'):
            self.retry(event, data)
        elif kind in ('session/title', 'session/title-llm-request'):
            _title_sources(self.artifact['events'], event, data, self.known)
        elif kind == 'command/run':
            identity = _text(_get(data, 'commandId'), 'commandId')
            if identity in self.commands:
                raise SessionFormatError('command/run repeats commandId ' + identity)
            self.commands.add(identity)
        elif kind == 'command/done':
            if _text(_get(data, 'commandId'), 'commandId') not in self.commands:
                raise SessionFormatError('command/done has no prior command/run')
            if _get(data, 'sourceEventSeq') is not UNDEFINED:
                seq = _earlier(data['sourceEventSeq'], event['seq'], 'command sourceEventSeq')
                source = self.artifact['events'][seq] if seq < len(self.artifact['events']) else {}
                if data.get('kind') != 'success' or source.get('type') in ('command/run', 'command/done'):
                    raise SessionFormatError('command/done has invalid sourceEventSeq')
        elif kind in ('compaction/start', 'compaction/summary', 'compaction/end', 'compaction/prune'):
            self.compact(event, data)
        elif kind == 'user/message':
            source = _record(_get(data, 'source'), 'user message source')
            if event.get('surfaceOp') != 'append' and source.get('kind') == 'compact-checkpoint':
                self.compaction_owner(source, 'compaction checkpoint')
        elif kind == 'session/end-seed':
            self.compaction = None


def _not_started_repair(event, data, message, call_id):
    error = _record(_get(data, 'error'), 'not-started error')
    if (error.get('name') != 'ToolNotStartedError' or error.get('code') != 'TOOL_NOT_STARTED'
            or message.get('isError') is not True or _get(event, 'sourceEventSeqs') is not UNDEFINED):
        return False
    identity = _text(_get(message, 'id'), 'not-started message id')
    if identity.startswith('forked-tool-result-' + call_id + '-'):
        return True
    prefix = 'interrupted-tool-result-' + call_id + '-'
    suffix = identity[len(prefix):]
    content = _array(_get(message, 'content'), 'not-started content')
    block = content[0] if content else None
    return (identity.startswith(prefix) and re.fullmatch(r'(0|[1-9][0-9]*)', suffix) is not None
        and int(suffix) <= 9007199254740991 and len(content) == 1 and isinstance(block, dict) and block.get('type') == 'text'
        and block.get('text') == 'The tool call was interrupted before the Harness recorded it as started. Retry it if it is still needed.')


def _title_sources(events, event, data, known):
    references = _array(_get(data, 'messageSeqs'), 'title messageSeqs')
    if event['type'] == 'session/title' and (len(references) == 0) != (_record(_get(data, 'source'), 'title source').get('kind') == 'user'):
        raise SessionFormatError('session/title messageSeqs must be empty exactly for a user title')
    seen = set()
    for value in references:
        seq = _earlier(value, event['seq'], 'title messageSeqs')
        source = events[seq] if seq < len(events) else None
        if (seq in seen or source is None or source['type'] != 'user/message' or source['type'] not in known
                or _record(_get(_record(source['data'], 'title input'), 'source'), 'title input source').get('kind') != 'user'):
            raise SessionFormatError(event['type'] + ' messageSeqs must cite distinct earlier human user/message events')
        seen.add(seq)
    if event['type'] != 'session/title-llm-request':
        return
    messages = _array(_get(data, 'messages'), 'title messages')
    message = _record(messages[0] if messages else UNDEFINED, 'title message')
    content = _array(_get(message, 'content'), 'title content')
    block = content[0] if content else None
    if (not references or len(messages) != 1 or message.get('role') != 'user'
            or _record(_get(message, 'source'), 'title source').get('kind') != 'dsh-session-title-llm'
            or len(content) != 1 or not isinstance(block, dict) or block.get('type') != 'text'):
        raise SessionFormatError('session/title-llm-request messages do not represent messageSeqs')


def assertV4LifecycleRelationships(artifact, knownEventTypes):
    state = Relationships(artifact, knownEventTypes)
    for event in artifact['events']:
        state.accept(event)
