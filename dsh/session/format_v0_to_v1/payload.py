"""Frozen released payload rules, independent of the installed plugin vocabulary.

Ported from rc.3 session-format-v0-to-v1/payload-validation.ts. Unknown nested
owner discriminants remain opaque; known variants have exact member rules.
"""
import datetime
import math
import re

from dsh.core.session.json import UNDEFINED
from dsh.cordis.utils import _js_strict_equal, js_to_string
from dsh.cordis.json_text import stringify_json
from dsh.cordis.text import trim_js
from dsh.session.format import SessionFormatError, sessionFormatCount, sessionFormatSafeInteger
from .codec import record, exact_keys


def compact(value):
    return stringify_json(value)


def equal_json(left, right):
    if isinstance(left, dict) or isinstance(right, dict):
        return isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys() and all(equal_json(left[key], right[key]) for key in left)
    if isinstance(left, list) or isinstance(right, list):
        return isinstance(left, list) and isinstance(right, list) and len(left) == len(right) and all(equal_json(a, b) for a, b in zip(left, right))
    return _js_strict_equal(left, right)


def exact(value, label, required, optional=()):
    value = record(value, label)
    exact_keys(value, required, optional, label)
    return value


def string(value, label):
    if not isinstance(value, str):
        raise SessionFormatError(label + ' must be a string')


def nonempty(value, label):
    if not isinstance(value, str) or not value:
        raise SessionFormatError(label + ' must be a non-empty string')


def boolean(value, label):
    if type(value) is not bool:
        raise SessionFormatError(label + ' must be a boolean')


count = sessionFormatCount
safe = sessionFormatSafeInteger


def positive(value, label):
    result = count(value, label)
    if result == 0:
        raise SessionFormatError(label + ' must be positive')
    return result


def finite(value, label):
    if type(value) not in (int, float) or abs(value) > 1.7976931348623157e308 or not math.isfinite(value) or (value == 0 and math.copysign(1, value) < 0):
        raise SessionFormatError(label + ' must be a finite number')
    return value


def literal(value, allowed, label):
    if not any(_js_strict_equal(value, candidate) for candidate in allowed):
        raise SessionFormatError(label + ' must be one of ' + ', '.join(js_to_string(v) for v in allowed))


def array(value, label, validate=None):
    if not isinstance(value, list):
        raise SessionFormatError(label + ' must be an array')
    if validate:
        for index, child in enumerate(value):
            validate(child, label + '[%s]' % index)
    return value


def fields(value, label, rules):
    for key, validate in rules.items():
        validate(value.get(key, UNDEFINED), label + ' ' + key)


def optional(value, label, rules):
    for key, validate in rules.items():
        if value.get(key, UNDEFINED) is not UNDEFINED:
            validate(value[key], label + ' ' + key)


def choice(*values):
    return lambda value, label: literal(value, values, label)


def earlier(value, seq, label):
    result = count(value, label)
    if result >= seq:
        raise SessionFormatError(label + ' must identify an earlier event')
    return result


def seq_array(value, seq, label, required):
    seen = set()
    def member(v, path):
        n = earlier(v, seq, path)
        if n in seen:
            raise SessionFormatError(label + ' repeats seq %s' % n)
        seen.add(n)
    values = array(value, label, member)
    if required and not values:
        raise SessionFormatError(label + ' must be non-empty')
    return values


def llm_failure(value, label):
    value = exact(value, label, ['message', 'code'], ['status', 'providerRetryAfterMs', 'requestId'])
    fields(value, label, dict(message=nonempty, code=nonempty))
    if 'status' in value:
        n = safe(value['status'], label + ' status')
        if n < 100 or n > 599:
            raise SessionFormatError(label + ' status must be 100 through 599')
    if 'providerRetryAfterMs' in value and finite(value['providerRetryAfterMs'], label + ' providerRetryAfterMs') <= 0:
        raise SessionFormatError(label + ' providerRetryAfterMs must be positive')
    optional(value, label, dict(requestId=nonempty))


def usage(value, label):
    value = exact(value, label, ['inputTokens', 'outputTokens'], ['totalTokens', 'cacheReadTokens', 'cacheWriteTokens', 'reasoningTokens'])
    fields(value, label, {key: count for key in value})


def content(value, label, version):
    array(value, label, lambda block, path: content_block(block, path, version))


def content_block(value, label, version):
    block = record(value, label)
    kind = block.get('type', UNDEFINED)
    if kind in ('text', 'reasoning'):
        exact_keys(block, ['type', 'text'], [], label)
        string(block['text'], label + ' text')
    elif kind == 'image':
        exact_keys(block, ['type', 'attachment'], [], label)
        image(block['attachment'], label + ' attachment')
    elif kind == 'tool-call':
        exact_keys(block, ['type', 'id', 'name', 'arguments'], [], label)
        fields(block, label, dict(id=nonempty, name=nonempty, arguments=string))
    elif kind == 'tool-result':
        exact_keys(block, ['type', 'toolCallId', 'content'], ['isError'], label)
        nonempty(block['toolCallId'], label + ' toolCallId')
        content(block['content'], label + ' content', version)
        optional(block, label, dict(isError=boolean))
    else:
        nonempty(kind, label + ' type')


def image(value, label):
    value = exact(value, label, ['attachmentId', 'mediaType', 'bytes', 'width', 'height'], ['name', 'originalDimensions'])
    fields(value, label, dict(attachmentId=nonempty, mediaType=choice('image/png', 'image/jpeg', 'image/webp', 'image/gif'), bytes=count, width=positive, height=positive))
    optional(value, label, dict(name=string))
    if 'originalDimensions' in value:
        dims = exact(value['originalDimensions'], label + ' originalDimensions', ['width', 'height'])
        fields(dims, label + ' original', dict(width=positive, height=positive))


def message(value, label, version, expected=None):
    value = exact(value, label, ['id', 'role', 'content', 'source'])
    nonempty(value['id'], label + ' id')
    role = 'assistant' if expected == 'assistant' else 'user' if expected in ('user', 'tool') else None
    literal(value['role'], [role] if role else ['system', 'user', 'assistant'], label + ' role')
    content(value['content'], label + ' content', version)
    source = record(value['source'], label + ' source')
    if version < 2 and expected == 'user' and source.get('kind') == 'goal' and source.get('change', UNDEFINED) is not UNDEFINED:
        legacy_goal_message(value, source, label)
    else:
        message_source(source, label + ' source', version, expected)
    if expected == 'tool':
        blocks = value['content']
        block = record(blocks[0], label + ' tool result') if len(blocks) == 1 else {}
        if block.get('type') != 'tool-result' or not _js_strict_equal(block.get('toolCallId', UNDEFINED), source.get('callId', UNDEFINED)):
            raise SessionFormatError(label + ' must contain exactly one tool-result block')


def legacy_goal_message(value, source, label):
    exact_keys(source, ['kind', 'goalId', 'revision', 'round', 'change'], [], label + ' source')
    fields(source, label + ' source', dict(goalId=nonempty, revision=positive))
    if not _js_strict_equal(source['round'], 0):
        raise SessionFormatError(label + ' legacy goal source round must be 0')
    change = record(source['change'], label + ' source change')
    goal_change(change, label + ' source change')
    ref = record(change['cleared'] if change['operation'] == 'clear' else change['goal'], label + ' source change ref')
    if source['goalId'] != ref['id'] or not _js_strict_equal(source['revision'], ref['revision']):
        raise SessionFormatError(label + ' legacy goal source does not match its change')
    keys = ['cleared', 'clearedAt'] if change['operation'] == 'clear' else ['goal', 'roundsStarted', 'createdAt', 'updatedAt']
    expected = [dict(type='text', text='<goal_state>' + compact({key: change[key] for key in keys}) + '</goal_state>')]
    if not equal_json(value['content'], expected):
        raise SessionFormatError(label + ' legacy goal content does not match its change')


def message_source(value, label, version, expected=None):
    source = record(value, label)
    kind = source.get('kind', UNDEFINED)
    if expected == 'assistant' and kind != 'model':
        raise SessionFormatError(label + ' must be model source')
    if expected == 'tool' and kind != 'tool':
        raise SessionFormatError(label + ' must be tool source')
    specifications = {
        'user': (['kind'], ['rpcId', 'clientTimeZone'], {}, dict(rpcId=nonempty, clientTimeZone=nonempty)),
        'model': (['kind', 'provider', 'model'], ['replayState'], dict(provider=nonempty, model=nonempty), {}),
        'tool': (['kind', 'callId'], [], dict(callId=nonempty), {}),
        'team-message': (['kind', 'teamId', 'messageId', 'senderId', 'senderName'], [], dict(teamId=nonempty, messageId=nonempty, senderId=nonempty, senderName=string), {}),
        'goal': (['kind', 'goalId', 'revision', 'round'], [], dict(goalId=nonempty, revision=positive, round=positive), {}),
        'skill-invocation': (['kind', 'name', 'form'], [], dict(name=nonempty, form=choice('instructions')), {}),
        'coordinator': (['kind', 'form', 'senderSessionId'], [], dict(form=choice('relay'), senderSessionId=nonempty), {}),
        'subagent-report': (['kind', 'form', 'senderSessionId'], [], dict(form=choice('relay'), senderSessionId=nonempty), {}),
        'subagent-settled': (['kind', 'form', 'summary', 'senderSessionId'], [], dict(form=choice('notice'), summary=string, senderSessionId=nonempty), {}),
        'webhook': (['kind', 'provider', 'source', 'deliveryId', 'ruleId', 'form', 'summary'], [], dict(provider=nonempty, source=nonempty, deliveryId=nonempty, ruleId=nonempty, form=choice('notice'), summary=string), {}),
    }
    spec = specifications.get(kind) if isinstance(kind, str) else None
    if spec:
        required, admitted, rules, extras = spec
        exact_keys(source, required, admitted, label)
        fields(source, label, rules)
        optional(source, label, extras)
    elif kind == 'plugin':
        plugin_source(source, label)
    elif kind == 'session-reference':
        session_reference(source, label, version)
    elif kind == 'agent-instructions':
        exact_keys(source, ['kind', 'form', 'changes'], ['baseline', 'baselineIdentity'], label)
        literal(source['form'], ['instructions'], label + ' form')
        optional(source, label, dict(baseline=choice(True), baselineIdentity=nonempty))
        def validate(v, path):
            v = exact(v, path, ['action', 'scope', 'path'], ['digest'])
            fields(v, path, dict(action=choice('set', 'replace', 'remove'), scope=string, path=string))
            optional(v, path, dict(digest=string))
        array(source['changes'], label + ' changes', validate)
    elif kind == 'skill-catalog':
        exact_keys(source, ['kind', 'form', 'entries'], ['update'], label)
        literal(source['form'], ['catalog'], label + ' form')
        optional(source, label, dict(update=choice(True)))
        def entry(v, path):
            v = exact(v, path, ['name', 'description'])
            fields(v, path, dict(name=nonempty, description=string))
        array(source['entries'], label + ' entries', entry)
    else:
        nonempty(kind, label + ' kind')


def plugin_source(source, label):
    extra = ['form', 'sections', 'summary']
    if source.get('plugin') == 'compact':
        extra += ['compactionId', 'sourceCommandId']
    exact_keys(source, ['kind', 'plugin'], extra, label)
    nonempty(source['plugin'], label + ' plugin')
    if source['plugin'] == 'compact':
        nonempty(source.get('compactionId', UNDEFINED), label + ' compactionId')
        optional(source, label, dict(sourceCommandId=nonempty))
    form = source.get('form', UNDEFINED)
    if form is UNDEFINED:
        return
    literal(form, ['instructions', 'catalog', 'snapshot', 'notice', 'relay', 'recall'], label + ' form')
    if form == 'snapshot':
        def section(v, path):
            v = exact(v, path, ['name', 'text'])
            fields(v, path, dict(name=nonempty, text=string))
        array(source.get('sections', UNDEFINED), label + ' sections', section)
    elif source.get('sections', UNDEFINED) is not UNDEFINED:
        raise SessionFormatError(label + ' sections require snapshot form')
    if form == 'notice':
        string(source.get('summary', UNDEFINED), label + ' summary')
    elif source.get('summary', UNDEFINED) is not UNDEFINED:
        raise SessionFormatError(label + ' summary requires notice form')


def session_reference(source, label, version):
    exact_keys(source, ['kind', 'form', 'version', 'references'], [], label)
    literal(source['form'], ['recall'], label + ' form')
    literal(source['version'], [1], label + ' version')
    seen = set()
    references = array(source['references'], label + ' references')
    for index, value in enumerate(references):
        path = label + ' references[%s]' % index
        value = exact(value, path, ['sessionId', 'label', 'capturedThroughSeq', 'compacted', 'originalMessages', 'retainedMessages', 'omittedMessages', 'omittedBytes', 'truncated', 'inputIndex'], ['capturedFormatVersion'] if version >= 1 else [])
        fields(value, path, dict(sessionId=nonempty, label=string))
        if value['capturedThroughSeq'] is not None:
            count(value['capturedThroughSeq'], path + ' capturedThroughSeq')
        if 'capturedFormatVersion' in value:
            n = count(value['capturedFormatVersion'], path + ' capturedFormatVersion')
            if n < 1 or n > version:
                raise SessionFormatError(path + ' capturedFormatVersion must be between 1 and %s' % version)
        boolean(value['compacted'], path + ' compacted')
        fields(value, path, {key: count for key in ['originalMessages', 'retainedMessages', 'omittedMessages', 'omittedBytes', 'inputIndex']})
        boolean(value['truncated'], path + ' truncated')
        if value['retainedMessages'] > value['originalMessages'] or value['omittedMessages'] != value['originalMessages'] - value['retainedMessages']:
            raise SessionFormatError(path + ' message counts are inconsistent')
        if value['truncated'] != (value['omittedMessages'] > 0 or value['omittedBytes'] > 0):
            raise SessionFormatError(path + ' truncated disagrees with omitted content')
        if value['inputIndex'] != index:
            raise SessionFormatError(label + ' inputIndex must match reference position')
        if value['sessionId'] in seen:
            raise SessionFormatError(label + ' repeats sessionId ' + value['sessionId'])
        seen.add(value['sessionId'])
    if not references:
        raise SessionFormatError(label + ' references must be non-empty')


def stream_chunk(value, label):
    value = record(value, label)
    kind = value.get('type', UNDEFINED)
    specs = {
        'block-start': (['type', 'index', 'blockType'], [], dict(index=count, blockType=nonempty)),
        'text-delta': (['type', 'index', 'text'], [], dict(index=count, text=string)),
        'reasoning-delta': (['type', 'index', 'text'], [], dict(index=count, text=string)),
        'tool-call-delta': (['type', 'index', 'id', 'argumentsDelta'], ['name'], dict(index=count, id=nonempty, argumentsDelta=string)),
        'block-end': (['type', 'index', 'block'], [], dict(index=count)),
        'usage': (['type', 'usage'], [], dict(usage=usage)),
        'finish': (['type', 'reason'], ['replayState'], dict(reason=finish_reason)),
    }
    spec = specs.get(kind) if isinstance(kind, str) else None
    if not spec:
        text = 'undefined' if kind is UNDEFINED else compact(kind)
        raise SessionFormatError(label + ' has unknown stream chunk type ' + text)
    exact_keys(value, spec[0], spec[1], label)
    fields(value, label, spec[2])
    if kind == 'tool-call-delta':
        optional(value, label, dict(name=string))
    elif kind == 'block-end':
        content_block(value['block'], label + ' block', 1)
    elif kind == 'finish' and 'replayState' in value:
        replay(value['replayState'], label + ' replayState')


def finish_reason(value, label):
    value = record(value, label)
    kind = value.get('kind', UNDEFINED)
    if kind in ('aborted', 'error'):
        exact_keys(value, ['kind', 'failure'], [], label)
        llm_failure(value['failure'], label + ' failure')
        return
    if kind in ('stop', 'tool-calls', 'max-tokens'):
        exact_keys(value, ['kind'], [], label)
    nonempty(kind, label + ' kind')


def replay(value, label):
    value = exact(value, label, ['response'], ['blocks'])
    if 'blocks' in value and not isinstance(value['blocks'], list):
        raise SessionFormatError(label + ' blocks must be an array')


def turn_reason(value, label):
    value = record(value, label)
    kind = value.get('kind', UNDEFINED)
    if kind in ('completed', 'blocked', 'max-tokens', 'interrupted'):
        exact_keys(value, ['kind'], [], label)
    elif kind == 'aborted':
        exact_keys(value, ['kind', 'reason'], [], label)
        cause = record(value['reason'], label + ' abort cause')
        if cause.get('kind') == 'hook':
            exact_keys(cause, ['kind', 'reason'], [], label + ' abort cause')
            string(cause['reason'], label + ' abort reason')
        else:
            exact_keys(cause, ['kind'], [], label + ' abort cause')
            literal(cause.get('kind', UNDEFINED), ['user', 'parent', 'disposed', 'legacy'], label + ' abort kind')
    elif kind == 'error':
        exact_keys(value, ['kind', 'error'], [], label)
        llm_failure(value['error'], label + ' error')
    else:
        nonempty(kind, label + ' kind')


def request_header(value, label):
    value = exact(value, label, ['config'], ['adapterDefaults', 'system', 'tools'])
    config = exact(value['config'], label + ' config', ['provider', 'model'], ['reasoningEffort', 'temperature', 'maxTokens', 'stop'])
    fields(config, label, dict(provider=nonempty, model=nonempty))
    optional(config, label, dict(reasoningEffort=nonempty, temperature=finite, maxTokens=positive, stop=lambda v, p: array(v, p, string)))
    if 'adapterDefaults' in value:
        defaults = exact(value['adapterDefaults'], label + ' adapterDefaults', [], ['reasoningEffort', 'maxTokens'])
        for key, marker in defaults.items():
            literal(marker, [True], label + ' adapterDefaults ' + key)
            if key not in config:
                raise SessionFormatError(label + ' adapter default ' + key + ' lacks config value')
    optional(value, label, dict(system=string))
    if 'tools' in value:
        def tool(v, path):
            v = exact(v, path, ['name', 'description', 'parameters'])
            fields(v, path, dict(name=nonempty, description=string))
            record(v['parameters'], path + ' parameters')
        array(value['tools'], label + ' tools', tool)


def shadowed(data, seq, label):
    span = exact(data.get('shadowedRange', UNDEFINED), label + ' shadowedRange', ['start', 'end'])
    start = earlier(span['start'], seq, label + ' shadowedRange start')
    end = earlier(span['end'], seq, label + ' shadowedRange end')
    seqs = seq_array(data.get('shadowedSeqs', UNDEFINED), seq, label + ' shadowedSeqs', True)
    if seqs[0] != start or seqs[-1] != end:
        raise SessionFormatError(label + ' shadowedRange must match shadowedSeqs endpoints')
    count(data.get('shadowedTokenCount', UNDEFINED), label + ' shadowedTokenCount')


def goal_ref(value, label):
    value = exact(value, label, ['id', 'revision'])
    fields(value, label, dict(id=nonempty, revision=positive))


def goal_snapshot(value, label):
    value = exact(value, label, ['id', 'revision', 'objective', 'phase', 'maxGoalRounds'], ['blockedReason'])
    fields(value, label, dict(id=nonempty, revision=positive, objective=nonempty, phase=choice('active', 'paused', 'blocked', 'complete'), maxGoalRounds=positive))
    if value['phase'] == 'blocked':
        reason = exact(value.get('blockedReason', UNDEFINED), label + ' blockedReason', ['code', 'message'])
        fields(reason, label + ' blocked', dict(code=nonempty, message=nonempty))
    elif value.get('blockedReason', UNDEFINED) is not UNDEFINED:
        raise SessionFormatError(label + ' blockedReason requires blocked phase')


def goal_change(data, label):
    literal(data.get('kind', UNDEFINED), ['goal/change'], label + ' kind')
    literal(data.get('version', UNDEFINED), [1], label + ' version')
    if data.get('operation') == 'clear':
        exact_keys(data, ['kind', 'version', 'operation', 'cleared', 'clearedAt'], [], label + ' data')
        goal_ref(data['cleared'], label + ' cleared')
        count(data['clearedAt'], label + ' clearedAt')
    else:
        exact_keys(data, ['kind', 'version', 'operation', 'goal', 'roundsStarted', 'createdAt', 'updatedAt'], [], label + ' data')
        literal(data['operation'], ['create', 'edit', 'pause', 'resume', 'complete', 'block'], label + ' operation')
        goal_snapshot(data['goal'], label + ' goal')
        fields(data, label, dict(roundsStarted=count, createdAt=count, updatedAt=count))


def schedule_id(value, label):
    nonempty(value, label)
    if trim_js(value) != value:
        raise SessionFormatError(label + ' must not have surrounding whitespace')


def instant(value, label):
    valid = isinstance(value, str) and re.fullmatch(r'(?!0000)\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}Z', value, re.ASCII)
    if valid:
        try:
            datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%fZ')
        except ValueError:
            valid = False
    if not valid:
        raise SessionFormatError(label + ' must be a canonical UTC instant')


def schedule_record(value, label):
    value = record(value, label)
    kind = value.get('kind')
    if kind in ('after', 'every'):
        key = 'afterSeconds' if kind == 'after' else 'everySeconds'
        exact_keys(value, ['id', 'kind', 'prompt', key, 'scheduledAt'], [], label)
        n = positive(value[key], label + ' ' + key)
        if kind == 'every' and n < 300:
            raise SessionFormatError(label + ' everySeconds must be at least 300')
    elif kind == 'at':
        exact_keys(value, ['id', 'kind', 'prompt', 'scheduledAt'], [], label)
    else:
        raise SessionFormatError(label + ' has unknown schedule kind')
    fields(value, label, dict(id=schedule_id, prompt=nonempty, scheduledAt=instant))


def schedule_change(data, label):
    literal(data.get('version', UNDEFINED), [1], label + ' version')
    if data.get('operation') == 'create':
        exact_keys(data, ['version', 'operation', 'schedule'], [], label + ' data')
        schedule_record(data['schedule'], label + ' schedule')
    else:
        exact_keys(data, ['version', 'operation', 'id'], ['acceptedAt'] if data.get('operation') == 'dispatch' else [], label + ' data')
        literal(data['operation'], ['delete', 'dispatch'], label + ' operation')
        schedule_id(data['id'], label + ' id')
        optional(data, label, dict(acceptedAt=instant))


def route(value, label):
    value = exact(value, label, ['provider', 'model'])
    fields(value, label, dict(provider=nonempty, model=nonempty))


def title_source(value, label):
    value = record(value, label)
    if value.get('kind') == 'provider':
        exact_keys(value, ['kind', 'provider'], ['model'], label)
        nonempty(value['provider'], label + ' provider')
        optional(value, label, dict(model=route))
    else:
        exact_keys(value, ['kind'], [], label)
        literal(value.get('kind', UNDEFINED), ['fallback', 'user'], label + ' kind')


SUBAGENT_DESCRIPTOR_VERSIONS = (1, 2, 3)


def descriptor(data, label):
    literal(data.get('version', UNDEFINED), SUBAGENT_DESCRIPTOR_VERSIONS, label + ' version')
    nonempty(data.get('provider', UNDEFINED), label + ' provider')
    composition = ['agentProvider', 'agentModel', 'persona', 'toolFilter']
    if data['version'] == 1:
        exact_keys(data, ['version', 'provider', 'label'], composition, label + ' data')
    elif data.get('mode') == 'one-shot':
        exact_keys(data, ['mode', 'version', 'provider'], ['label'], label + ' data')
        optional(data, label, dict(label=string))
        return
    else:
        literal(data.get('mode', UNDEFINED), ['continuable'], label + ' mode')
        exact_keys(data, ['mode', 'version', 'provider', 'label'],
                   composition + (['agentReasoningEffort'] if data['version'] == 3 else []), label + ' data')
    strict = data['version'] == 3
    string_field = nonempty if strict else string
    string_field(data.get('label', UNDEFINED), label + ' label')
    optional(data, label, {key: string_field for key in ['agentProvider', 'agentModel', 'agentReasoningEffort', 'persona']})
    if strict and ('agentProvider' in data) != ('agentModel' in data):
        raise SessionFormatError(label + ' agentProvider and agentModel must be paired')
    if 'toolFilter' in data:
        value = exact(data['toolFilter'], label + ' toolFilter', [], ['allow', 'deny'])
        if not value:
            raise SessionFormatError(label + ' toolFilter requires allow or deny')
        for key in ['allow', 'deny']:
            if key in value:
                array(value[key], label + ' ' + key, string_field)


def allowed_models(value, label):
    seen = set()
    def validate(v, path):
        route(v, path)
        key = v['provider'] + '\0' + v['model']
        if key in seen:
            raise SessionFormatError(label + ' repeats route ' + key)
        seen.add(key)
    if not array(value, label, validate):
        raise SessionFormatError(label + ' must be non-empty')


def team_member(value, label):
    value = exact(value, label, ['id', 'name', 'description', 'provider', 'context', 'phase'], ['error'])
    fields(value, label, dict(id=nonempty, name=string, description=string, provider=string, context=choice('fresh', 'fork'), phase=choice('provisioning', 'active', 'failed')))
    optional(value, label, dict(error=string))


def team_task(value, label):
    value = exact(value, label, ['id', 'revision', 'subject', 'description', 'status', 'blockedBy', 'writeScopes'], ['ownerId'])
    fields(value, label, dict(id=nonempty, revision=positive, subject=string, description=string, status=choice('pending', 'in_progress', 'completed', 'deleted')))
    optional(value, label, dict(ownerId=nonempty))
    array(value['blockedBy'], label + ' blockedBy', nonempty)
    array(value['writeScopes'], label + ' writeScopes', string)


def team_message(value, label, version):
    value = exact(value, label, ['id', 'senderId', 'senderName', 'targetId', 'delivery', 'content'])
    fields(value, label, dict(id=nonempty, senderId=nonempty, targetId=nonempty, senderName=string, delivery=choice('quiet', 'wakeup')))
    content(value['content'], label + ' content', version)


def search_body(value, label):
    value = exact(value, label, ['model', 'max_tokens', 'messages', 'tools'])
    fields(value, label, dict(model=nonempty, max_tokens=positive))
    def validate_message(v, path):
        v = exact(v, path, ['role', 'content'])
        literal(v['role'], ['user'], path + ' role')
        def text(block, p):
            block = exact(block, p, ['type', 'text'])
            fields(block, p, dict(type=choice('text'), text=string))
        if len(array(v['content'], path + ' content', text)) != 1:
            raise SessionFormatError(path + ' content must contain one text block')
    if len(array(value['messages'], label + ' messages', validate_message)) != 1:
        raise SessionFormatError(label + ' messages must contain one user message')
    def validate_tool(v, path):
        v = exact(v, path, ['type', 'name', 'max_uses'])
        fields(v, path, dict(type=choice('web_search_20250305'), name=choice('web_search'), max_uses=positive))
    if len(array(value['tools'], label + ' tools', validate_tool)) != 1:
        raise SessionFormatError(label + ' tools must contain one web search tool')


def assertReleasedPayloadSemantics(event, version):
    kind, seq = event['type'], event['seq']
    data = record(event['data'], '%s %s data' % (kind, js_to_string(seq)))
    label = '%s %s' % (kind, js_to_string(seq))
    simple = {
        'agent-preset/selected': (dict(agentPreset=string), {}),
        'approval/asked': (dict(id=nonempty, toolName=nonempty), dict(callId=nonempty, reason=string)),
        'approval/decided': (dict(id=nonempty, outcome=choice('allowed-once', 'rejected', 'cancelled', 'unavailable')), {}),
        'approval/policy': (dict(policy=choice('ask', 'never')), dict(source=choice('delegation'))),
        'feedback/record': (dict(text=nonempty), {}),
        'hook/invoked': (dict(turn=count, point=nonempty, dialect=choice('claude-code', 'codex'), handlerId=nonempty), dict(matcher=string)),
        'model/selection': (dict(provider=nonempty, model=nonempty), dict(reasoningEffort=nonempty)),
        'permission/preset': (dict(preset=nonempty), {}),
        'plan/mode': (dict(active=boolean), {}),
        'request/context': (dict(provider=nonempty, model=nonempty), dict(contextWindow=positive)),
        'request/header': (dict(header=request_header, reason=choice('initial', 'resume', 'change', 'series')), dict(startsSeries=choice(True))),
        'sandbox/mode': (dict(mode=choice('read-only', 'workspace-write', 'danger-full-access')), dict(source=choice('delegation'))),
        'subagent/model-selection-policy': (dict(allowedModels=allowed_models), {}),
        'tool-workflow/agent-end': (dict(runId=nonempty, seq=positive, outcome=choice('completed', 'failed', 'cancelled')), {}),
        'tool-workflow/agent-start': (dict(runId=nonempty, seq=positive, label=string, childId=nonempty), dict(phase=string)),
        'tool-workflow/run-end': (dict(runId=nonempty, stopReason=choice('completed', 'cancelled', 'error')), {}),
        'tool-workflow/run-start': (dict(runId=nonempty, name=nonempty), {}),
        'tool/call': (dict(turn=count, step=count, callId=nonempty, name=nonempty, arguments=string), {}),
        'step/start': (dict(turn=count, step=count), {}),
        'step/end': (dict(turn=count, step=count), {}),
        'turn/start': (dict(turn=count), {}),
        'turn/end': (dict(turn=count, reason=turn_reason), {}),
        'web/deepseek-search-llm-request': (dict(endpoint=nonempty, apiVersion=nonempty, body=search_body), {}),
    }
    if kind in simple:
        rules, extras = simple[kind]
        fields(data, label, rules)
        optional(data, label, extras)
    elif kind == 'agent/inbox/spliced':
        fields(data, label, dict(target=choice('next-turn', 'next-step'), start=count))
        optional(data, label, dict(removedCount=count))
        array(data.get('inserted', UNDEFINED), label + ' inserted', lambda v, p: message(v, label + ' inserted message', version, 'user'))
        optional(data, label, dict(outcome=choice('canceled')))
    elif kind in ('assistant/chunk', 'assistant/message', 'tool/result'):
        fields(data, label, dict(turn=count, step=count))
        if kind == 'assistant/chunk':
            stream_chunk(data.get('chunk', UNDEFINED), label + ' chunk')
        else:
            message(data.get('message', UNDEFINED), label + ' message', version, 'assistant' if kind == 'assistant/message' else 'tool')
            if kind == 'assistant/message':
                optional(data, label, dict(usage=usage, interrupted=choice(True)))
            elif 'error' in data:
                error = exact(data['error'], label + ' error', ['name', 'code'])
                fields(error, label + ' error', dict(name=nonempty, code=nonempty))
    elif kind == 'command/done':
        fields(data, label, dict(commandId=nonempty, kind=choice('success', 'error')))
        optional(data, label, dict(text=string, sourceEventSeq=lambda v, p: earlier(v, seq, p)))
    elif kind == 'command/run':
        fields(data, label, dict(commandId=nonempty, name=nonempty))
        optional(data, label, dict(args=string))
        source = exact(data.get('source', UNDEFINED), label + ' source', ['kind'])
        literal(source['kind'], ['user'], label + ' source kind')
    elif kind in ('compaction/start', 'compaction/end'):
        nonempty(data.get('compactionId', UNDEFINED), label + ' compactionId')
        optional(data, label, dict(sourceCommandId=nonempty))
        if data.get('turn', UNDEFINED) is not None:
            count(data.get('turn', UNDEFINED), label + ' turn')
        optional(data, label, dict(error=string))
    elif kind == 'compaction/prune':
        shadowed(data, seq, label)
    elif kind == 'compaction/summary':
        if data.get('llmStreamCall') is True and 'rawOutput' not in data:
            raise SessionFormatError(label + ' llmStreamCall requires rawOutput')
        nonempty(data.get('compactionId', UNDEFINED), label + ' compactionId')
        optional(data, label, dict(sourceCommandId=nonempty))
        content(data.get('summary', UNDEFINED), label + ' summary', version)
        shadowed(data, seq, label)
        fields(data, label, dict(provider=nonempty, model=nonempty))
        optional(data, label, dict(maxTokens=count, usage=usage))
        if 'rawOutput' in data:
            content(data['rawOutput'], label + ' rawOutput', version)
        optional(data, label, dict(llmStreamCall=choice(True)))
    elif kind == 'goal/change':
        goal_change(data, label)
    elif kind == 'hook/result':
        fields(data, label, dict(turn=count, point=nonempty, handlerId=nonempty, decision=nonempty))
        optional(data, label, dict(exitCode=safe, stderrSummary=string))
        if finite(data.get('durationMs', UNDEFINED), label + ' durationMs') < 0:
            raise SessionFormatError(label + ' durationMs must be non-negative')
    elif kind == 'llm/retry':
        fields(data, label, dict(retryId=nonempty, turn=count, step=count, provider=nonempty, mode=choice('normal', 'always'), policyKey=nonempty, retry=positive))
        if data['mode'] == 'normal':
            n = positive(data.get('maxRetries', UNDEFINED), label + ' maxRetries')
            if data['retry'] > n:
                raise SessionFormatError(label + ' retry exceeds maxRetries')
        elif 'maxRetries' in data:
            raise SessionFormatError(label + ' always mode must omit maxRetries')
        delay = finite(data.get('delayMs', UNDEFINED), label + ' delayMs')
        if delay < 0:
            raise SessionFormatError(label + ' delayMs must be non-negative')
        if delay > 2147483647:
            raise SessionFormatError(label + ' delayMs exceeds the timer range')
        llm_failure(data.get('failure', UNDEFINED), label + ' failure')
    elif kind == 'llm/retry-started':
        fields(data, label, dict(retryId=nonempty, turn=count, step=count, retry=positive))
    elif kind == 'schedule/change':
        schedule_change(data, label)
    elif kind == 'session-log-deepseek/delivery-accepted':
        accepted = 0 if 'sessionFormatVersion' not in data else count(data['sessionFormatVersion'], label + ' sessionFormatVersion')
        if _js_strict_equal(accepted, version):
            nonempty(data.get('sessionId', UNDEFINED), label + ' sessionId')
            earlier(data.get('throughSeq', UNDEFINED), seq, label + ' throughSeq')
    elif kind == 'session/end-seed':
        pass
    elif kind == 'session/title':
        nonempty(data.get('title', UNDEFINED), label + ' title')
        seq_array(data.get('messageSeqs', UNDEFINED), seq, label + ' messageSeqs', False)
        title_source(data.get('source', UNDEFINED), label + ' source')
    elif kind == 'session/title-llm-request':
        nonempty(data.get('titleProvider', UNDEFINED), label + ' titleProvider')
        seq_array(data.get('messageSeqs', UNDEFINED), seq, label + ' messageSeqs', True)
        route(data.get('route', UNDEFINED), label + ' route')
        string(data.get('system', UNDEFINED), label + ' system')
        array(data.get('messages', UNDEFINED), label + ' messages', lambda v, p: message(v, label + ' message', version))
        positive(data.get('maxTokens', UNDEFINED), label + ' maxTokens')
    elif kind == 'subagent/descriptor':
        descriptor(data, label)
    elif kind.startswith('team/'):
        fields(data, label, dict(version=choice(1), teamId=nonempty))
        if kind == 'team/member':
            team_member(data.get('member', UNDEFINED), label + ' member')
        elif kind == 'team/task':
            team_task(data.get('task', UNDEFINED), label + ' task')
        elif kind == 'team/message/queued':
            team_message(data.get('message', UNDEFINED), label + ' message', version)
        elif kind == 'team/message/delivered':
            fields(data, label, dict(messageId=nonempty, targetId=nonempty))
        else:
            raise SessionFormatError('released payload validator is missing event ' + compact(kind))
    elif kind == 'todo/write':
        def todo(v, path):
            v = exact(v, path, ['content', 'status'])
            fields(v, path, dict(content=string, status=choice('pending', 'in_progress', 'completed')))
        array(data.get('todos', UNDEFINED), label + ' todos', todo)
    elif kind in ('tool/code-dispatch', 'tool/code-dispatch-start'):
        fields(data, label, dict(rootCallId=nonempty, parentCallId=nonempty, subCallId=nonempty, name=nonempty))
        if kind == 'tool/code-dispatch':
            boolean(data.get('isError', UNDEFINED), label + ' isError')
            content(data.get('content', UNDEFINED), label + ' content', version)
    elif kind == 'user/message':
        message(data, label, version, 'user')
    else:
        raise SessionFormatError('released payload validator is missing event ' + compact(kind))
