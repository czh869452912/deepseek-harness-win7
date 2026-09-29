"""pi-ai event translation, including native replay and terminal failures."""
import json
import re

from dsh.core.cancellation import aborted
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_replay import replay_state
from dsh.llm.provider_errors import is_context_window_exceeded, is_quota_exceeded


OVERFLOW = [r'prompt is too long', r'request_too_large', r'input is too long for requested model',
    r'exceeds the context window', r"exceeds (?:the )?(?:model'?s )?maximum context length(?: of [\d,]+ tokens?|\s*\([\d,]+\))",
    r'input token count.*exceeds the maximum', r'maximum prompt length is \d+', r'reduce the length of the messages',
    r'maximum context length is \d+ tokens', r'exceeds (?:the )?maximum allowed input length of [\d,]+ tokens?',
    r"input \(\d+ tokens\) is longer than the model'?s context length \(\d+ tokens\)",
    r'exceeds the limit of \d+', r'exceeds the available context size', r'greater than the context length',
    r'context window exceeds limit', r'exceeded model token limit', r'prompt has [\d,]+ tokens?, but the configured context size is [\d,]+ tokens?',
    r'too large for model with \d+ maximum context length', r'model_context_window_exceeded', r'prompt too long; exceeded (?:max )?context length',
    r'range of input length should be', r'context[_ ]length[_ ]exceeded', r'too many tokens', r'token limit exceeded',
    r'^4(?:00|13)\s*(?:status code)?\s*\(no body\)']


def usage(value):
    result = dict(inputTokens=value['input'], outputTokens=value['output'], totalTokens=value['totalTokens'])
    for source, target in (('cacheRead', 'cacheReadTokens'), ('cacheWrite', 'cacheWriteTokens')):
        if value[source] > 0:
            result[target] = value[source]
    return result


def classify(message):
    if re.search(r'\b(?:401|403)\b', message):
        return 'AUTH'
    if is_quota_exceeded(message):
        return 'QUOTA'
    for pattern, code in [
        (r'\b429\b|rate.?limit', 'RATE_LIMIT'),
        (r'\b413\b|failed to buffer the request body:\s*length limit exceeded|payload too large|request body too large|\b400\b|invalid.?request', 'INVALID_REQUEST'),
        (r'\b5\d\d\b', 'SERVER'), (r'\btime(?:d)?\s*out\b|timeout', 'TIMEOUT'),
        (r'stream ended (?:before|without)\b|\b(?:network|connection|socket|fetch)\b|\bECONN[A-Z]+\b|\b(?:other side closed|HTTP2 request did not get a response|WebSocket closed unexpectedly)\b|\bterminated\b|premature close', 'TRANSPORT')]:
        if re.search(pattern, message, re.I):
            return code
    return 'PI_AI_ERROR'


def stop_reason(message, context_window=None):
    stop = message['stopReason']
    detail = message.get('errorMessage', '')
    counts = message['usage']
    total_input = counts['input'] + counts['cacheRead']
    overflow = (stop == 'error' and (is_context_window_exceeded(detail) or
        (not re.search(r'^(Throttling error|Service unavailable):|rate limit|too many requests', detail, re.I)
         and any(re.search(pattern, detail, re.I) for pattern in OVERFLOW))))
    if context_window and ((stop == 'stop' and total_input > context_window) or
                          (stop == 'length' and counts['output'] == 0 and total_input >= context_window * .99)):
        overflow = True
    if overflow:
        return dict(kind='error', failure=dict(message=detail or 'pi-ai detected context overflow for model "{}"'.format(message['model']), code='CONTEXT_WINDOW_EXCEEDED'))
    if stop == 'stop' and message['content']:
        return dict(kind='stop')
    if stop in ('length', 'toolUse'):
        return dict(kind='max-tokens' if stop == 'length' else 'tool-calls')
    if stop == 'stop':
        detail, code = 'model "{}" returned a completed response with no content'.format(message['model']), 'EMPTY_RESPONSE'
    elif stop == 'aborted':
        return dict(kind='aborted', failure=dict(message=detail or 'pi-ai stream aborted', code='ABORTED'))
    elif stop == 'pending':
        detail, code = 'pi-ai stream for model "{}" ended pending'.format(message['model']), 'PI_AI_ERROR'
    elif stop == 'deferred':
        detail, code = 'pi-ai deferred response for model "{}" is not supported'.format(message['model']), 'PI_AI_ERROR'
    else:
        detail = detail or 'pi-ai stream error'
        code = classify(detail)
    return dict(kind='error', failure=dict(message=detail, code=code))


async def to_stream_chunks(events, context_window=None, signal=None):
    tools = {}
    async for event in events:
        kind, index = event['type'], event.get('contentIndex')
        if kind in ('text_start', 'thinking_start', 'toolcall_start'):
            if kind == 'toolcall_start':
                content = event['partial']['content']
                block = content[index] if index < len(content) else {}
                tools[index] = dict(id=block['id'], name=block['name']) if block.get('type') == 'toolCall' else dict(id='', name='')
            yield dict(type='block-start', index=index, blockType={'text_start': 'text', 'thinking_start': 'reasoning', 'toolcall_start': 'tool-call'}[kind])
        elif kind in ('text_delta', 'thinking_delta'):
            yield dict(type='text-delta' if kind == 'text_delta' else 'reasoning-delta', index=index, text=event['delta'])
        elif kind in ('text_end', 'thinking_end'):
            yield dict(type='block-end', index=index, block=dict(type='text' if kind == 'text_end' else 'reasoning', text=event['content']))
        elif kind == 'toolcall_delta':
            known = tools.get(index, {})
            yield dict(type='tool-call-delta', index=index, id=known.get('id', ''), argumentsDelta=event['delta'],
                **(dict(name=known['name']) if known.get('name') else {}))
        elif kind == 'toolcall_end':
            block = event['toolCall']
            yield dict(type='block-end', index=index, block=dict(type='tool-call', id=block['id'], name=block['name'],
                arguments=json.dumps(block['arguments'], ensure_ascii=False, separators=(',', ':'))))
        elif kind in ('done', 'error'):
            message = event['message' if kind == 'done' else 'error']
            yield dict(type='usage', usage=usage(message['usage']))
            effective = dict(message, stopReason='aborted') if kind == 'error' and aborted(signal) else message
            finish = dict(type='finish', reason=stop_reason(effective, context_window))
            if kind == 'done':
                finish['replayState'] = replay_state(message)
            yield finish
            return
    raise LlmError('pi-ai event stream ended without done/error', 'STREAM_CLOSED')
