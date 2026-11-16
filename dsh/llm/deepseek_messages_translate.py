"""Messages event state machine with ordered blocks, usage and one terminal finish."""
import copy

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _UNDEFINED, js_to_string
from dsh.llm.deepseek_messages_replay import object_value,replayState
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_json import loads


def _string(value):
    if not isinstance(value,str): raise LlmError('DeepSeek Messages expected a string field','MALFORMED_RESPONSE')
    return value


def _malformed(detail): raise LlmError('DeepSeek Messages stream: '+detail,'MALFORMED_RESPONSE')


def _safe_nonnegative(value):
    return type(value) in (int,float) and 0 <= value <= 9007199254740991 and int(value) == value


def _index(event):
    value = event.get('index')
    if not _safe_nonnegative(value): _malformed('invalid block index')
    return value


def _usage(usage, raw):
    fields = object_value(raw)
    for wire,local in [('input_tokens','inputTokens'),('output_tokens','outputTokens'),('cache_read_input_tokens','cacheReadTokens'),('cache_creation_input_tokens','cacheWriteTokens')]:
        if wire not in fields: continue
        if not _safe_nonnegative(fields[wire]): _malformed('invalid '+wire)
        usage[local] = fields[wire]


def _start(event, index):
    native = object_value(event.get('content_block'))
    kind = native.get('type',_UNDEFINED)
    if kind == 'text': content,replay = dict(type='text',text=_string(native.get('text'))),dict(type='text')
    elif kind == 'thinking':
        content,replay = dict(type='reasoning',text=_string(native.get('thinking'))),dict(type='reasoning')
        if 'signature' in native: replay['signature'] = _string(native['signature'])
    elif kind == 'tool_use':
        content = dict(type='tool-call',id=_string(native.get('id')),name=_string(native.get('name')),arguments=stringify_json(object_value(native.get('input'))))
        if not content['id'] or not content['name']: _malformed('empty tool identity')
        replay = dict(type='tool-call')
    else: raise LlmError('DeepSeek Messages does not support response block '+js_to_string(kind),'UNSUPPORTED_CONTENT')
    return dict(index=index,content=content,replay=replay,closed=False,json='')


def _delta(block, raw):
    delta,content = object_value(raw),block['content']
    kind = delta.get('type',_UNDEFINED)
    if (kind == 'text_delta' and content['type'] == 'text') or (kind == 'thinking_delta' and content['type'] == 'reasoning'):
        text = _string(delta.get('text' if kind == 'text_delta' else 'thinking'))
        content['text'] += text
        return dict(type='text-delta' if kind == 'text_delta' else 'reasoning-delta',index=block['index'],text=text)
    if kind == 'signature_delta' and content['type'] == 'reasoning':
        block['replay']['signature'] = block['replay'].get('signature','')+_string(delta.get('signature'))
        return None
    if kind == 'input_json_delta' and content['type'] == 'tool-call':
        text = _string(delta.get('partial_json'));block['json'] += text
        return dict(type='tool-call-delta',index=block['index'],id=content['id'],argumentsDelta=text)
    _malformed('unsupported delta '+js_to_string(kind)+' for '+content['type'])


async def translate(events, model):
    blocks,usage,started,reason = {},dict(inputTokens=0,outputTokens=0),False,None
    async for event in events:
        kind = event.get('type')
        if kind == 'message_start':
            if started: _malformed('duplicate message_start')
            _usage(usage,object_value(event.get('message')).get('usage'));started = True
            continue
        if kind not in ('content_block_start','content_block_delta','content_block_stop','message_delta','message_stop'): continue
        if not started: _malformed('event precedes message_start')
        if kind == 'content_block_start':
            wire_index = _index(event)
            if wire_index in blocks or reason is not None: _malformed('block starts after settlement or repeats an index')
            block = _start(event,len(blocks));blocks[wire_index] = block
            content = block['content']
            yield dict(type='block-start',index=block['index'],blockType=content['type'])
            if content['type'] in ('text','reasoning'):
                if content['text']: yield dict(type='text-delta' if content['type'] == 'text' else 'reasoning-delta',index=block['index'],text=content['text'])
            else: yield dict(type='tool-call-delta',index=block['index'],id=content['id'],name=content['name'],argumentsDelta='')
        elif kind in ('content_block_delta','content_block_stop'):
            block = blocks.get(_index(event))
            if block is None or block['closed']: _malformed('delta/stop without an open block')
            if kind == 'content_block_delta':
                chunk = _delta(block,event.get('delta'))
                if chunk is not None: yield chunk
            else:
                block['closed'] = True
                if block['content']['type'] == 'tool-call' and block['json']: block['content']['arguments'] = block['json']
                yield dict(type='block-end',index=block['index'],block=copy.deepcopy(block['content']))
        elif kind == 'message_delta':
            delta = object_value(event.get('delta'))
            raw = delta.get('stop_reason')
            if raw is not None:
                reasons = {'end_turn':'stop','stop_sequence':'stop','tool_use':'tool-calls','max_tokens':'max-tokens'}
                if not isinstance(raw,str) or raw not in reasons: _malformed('unsupported stop reason '+js_to_string(raw))
                reason = dict(kind=reasons[raw])
            if 'usage' in event: _usage(usage,event['usage'])
        else:
            if reason is None or any(not block['closed'] for block in blocks.values()): _malformed('message_stop without settled blocks and stop reason')
            if not blocks and reason['kind'] == 'stop': raise LlmError('DeepSeek Messages returned no content','EMPTY_RESPONSE')
            if reason['kind'] != 'max-tokens':
                for block in blocks.values():
                    content = block['content']
                    if content['type'] != 'tool-call': continue
                    try: parsed = loads(content['arguments'])
                    except Exception: _malformed('tool input is invalid JSON')
                    object_value(parsed)
            usage['totalTokens'] = int(float(usage['inputTokens'])+float(usage['outputTokens'])+float(usage.get('cacheReadTokens',0))+float(usage.get('cacheWriteTokens',0)))
            yield dict(type='usage',usage=copy.deepcopy(usage))
            yield dict(type='finish',reason=reason,replayState=replayState(model,[copy.deepcopy(block['replay']) for block in blocks.values()]))
            return
    raise LlmError('DeepSeek Messages stream ended before message_stop','STREAM_CLOSED')
