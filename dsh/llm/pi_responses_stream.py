"""Native Responses SSE adapter, ported from pi-ai (PI_AI_LICENSE.txt)."""
import urllib.error
import urllib.request

from dsh.core.cancellation import aborted
from dsh.llm.deepseek_wire import parse_sse
from dsh.llm.http_stream import open_stream
from dsh.llm.pi_completions_stream import _HeaderDeadline
from dsh.llm.pi_json import dumps, loads, parse_streaming_json
from dsh.llm.pi_replay import empty_usage
from dsh.llm.pi_responses_params import build_responses_params


class ResponsesDecoder:
    def __init__(self, model):
        self.model = model
        self.output = dict(role='assistant', content=[], api=model['api'], provider=model['provider'],
                           model=model['id'], usage=empty_usage(), stopReason='pending', timestamp=0)
        self.slots, self.reasoning = {}, {}
        self.terminal = False

    def event(self, kind, index=None, **data):
        return dict(type=kind, partial=self.output, **({'contentIndex': index} if index is not None else {}), **data)

    def create(self, index, item):
        kind = item['type']
        if kind == 'reasoning':
            block, tag = dict(type='thinking', thinking=''), 'thinking'
        elif kind == 'message':
            block, tag = dict(type='text', text=''), 'text'
            if item.get('phase') == 'final_answer':
                self.output['stopReason'] = 'stop'
        elif kind in ('function_call', 'custom_tool_call'):
            block, tag = dict(type='toolCall', id=item['call_id'] + '|' + item['id'], name=item['name'], arguments={}), 'toolcall'
            if 'namespace' in item:
                block['namespace'] = item['namespace']
            if kind == 'function_call':
                block['partialJson'] = item.get('arguments') or ''
            else:
                block['arguments'] = dict(input=item.get('input') or '')
                block['customInput'] = dict(input='', started=False, closed=False)
        else:
            return
        offset = len(self.output['content'])
        self.output['content'].append(block)
        self.slots[index] = (offset, tag, block)
        yield self.event(tag + '_start', offset)

    def custom_delta(self, block, text, close):
        state = block['customInput']
        delta = '' if state['started'] else '{"input":"'
        if text.startswith(state['input']):
            delta += dumps(text[len(state['input']):])[1:-1]
        if close and not state['closed']:
            delta += '"}'
        state.update(input=text, started=True, closed=close)
        block['arguments'] = dict(input=text)
        return delta

    def finalize(self, response):
        self.terminal = True
        output = self.output
        for item in response.get('output', []):
            block = self.reasoning.get(item.get('id'))
            if item.get('type') == 'reasoning' and item.get('encrypted_content') and block and block.get('thinkingSignature'):
                prior = loads(block['thinkingSignature'])
                if not prior.get('encrypted_content'):
                    block['thinkingSignature'] = dumps(dict(prior, encrypted_content=item['encrypted_content']))
        if response.get('id'):
            output['responseId'] = response['id']
        raw = response.get('usage')
        if raw:
            details = raw.get('input_tokens_details') or {}
            cached, writes = details.get('cached_tokens') or 0, details.get('cache_write_tokens') or 0
            output['usage'] = dict(input=max(0, (raw.get('input_tokens') or 0) - cached - writes),
                output=raw.get('output_tokens') or 0, cacheRead=cached, cacheWrite=writes,
                reasoning=(raw.get('output_tokens_details') or {}).get('reasoning_tokens') or 0, totalTokens=raw.get('total_tokens') or 0)
        usage = output['usage']
        tier = response.get('service_tier')
        multiplier = .5 if tier == 'flex' else (2.5 if self.model['id'] == 'gpt-5.5' else 2) if tier == 'priority' else 1
        usage['cost'] = {key: usage[key] * self.model.get('cost', {}).get(key, 0) / 1000000 * multiplier
                         for key in ('input', 'output', 'cacheRead', 'cacheWrite')}
        usage['cost']['total'] = sum(usage['cost'].values())
        status = response.get('status')
        reason = (response.get('incomplete_details') or {}).get('reason')
        if status is not None:
            output['rawStopReason'] = status + '.' + reason if reason else status
        if not status or status in ('completed', 'queued', 'in_progress'):
            output['stopReason'] = 'toolUse' if any(block['type'] == 'toolCall' for block in output['content']) else 'stop'
        elif status == 'incomplete' and reason == 'max_output_tokens':
            output['stopReason'] = 'length'
        else:
            output['stopReason'] = 'error'
            if status == 'incomplete':
                output['errorMessage'] = 'Response incomplete: ' + reason if reason else 'Response incomplete without a provider reason'
            elif status not in ('failed', 'cancelled'):
                raise ValueError('Unhandled stop reason: ' + str(status))

    def feed(self, event):
        kind, index = event.get('type'), event.get('output_index')
        if kind == 'response.created':
            self.output['responseId'] = event['response']['id']
        elif kind == 'response.output_item.added':
            yield from self.create(index, event['item'])
        elif kind == 'response.output_item.done':
            item = event['item']
            if item['type'] == 'message' and item.get('phase') == 'final_answer':
                self.output['stopReason'] = 'stop'
            if index not in self.slots:
                yield from self.create(index, item)
            if index not in self.slots:
                return
            offset, tag, block = self.slots[index]
            if tag == 'thinking' and item['type'] == 'reasoning':
                block['thinking'] = ('\n\n'.join(part['text'] for part in item.get('summary', [])) or
                    '\n\n'.join(part['text'] for part in item.get('content', [])) or block['thinking'])
                block['thinkingSignature'] = dumps(item)
                self.reasoning[item['id']] = block
                yield self.event('thinking_end', offset, content=block['thinking'])
            elif tag == 'text' and item['type'] == 'message':
                block['text'] = ''.join(part['text'] if part['type'] == 'output_text' else part['refusal'] for part in item.get('content', []))
                signature = dict(v=1, id=item['id'])
                if item.get('phase'):
                    signature['phase'] = item['phase']
                block['textSignature'] = dumps(signature)
                yield self.event('text_end', offset, content=block['text'])
            elif tag == 'toolcall' and item['type'] in ('function_call', 'custom_tool_call'):
                if item['type'] == 'function_call' and 'partialJson' in block:
                    block['arguments'] = parse_streaming_json(item.get('arguments') or block.pop('partialJson') or '{}')
                    block.pop('partialJson', None)
                elif 'customInput' in block:
                    delta = self.custom_delta(block, item.get('input', block['arguments']['input']), True)
                    if delta:
                        yield self.event('toolcall_delta', offset, delta=delta)
                    block.pop('customInput')
                if 'namespace' in item:
                    block['namespace'] = item['namespace']
                yield self.event('toolcall_end', offset, toolCall=block)
            self.slots.pop(index, None)
        elif kind in ('response.completed', 'response.incomplete'):
            self.finalize(event['response'])
        elif kind == 'error':
            raise ValueError('Error Code {}: {}'.format(event.get('code', 'undefined'), event.get('message', 'undefined')))
        elif kind == 'response.failed':
            self.terminal = True
            response = event.get('response') or {}
            if 'status' in response:
                self.output['rawStopReason'] = response['status']
            error, reason = response.get('error'), (response.get('incomplete_details') or {}).get('reason')
            raise ValueError('{}: {}'.format(error.get('code') or 'unknown', error.get('message') or 'no message') if error else
                             'incomplete: ' + reason if reason else 'Unknown error (no error details in response)')
        elif index in self.slots:
            offset, tag, block = self.slots[index]
            if tag == 'thinking' and kind in ('response.reasoning_summary_text.delta', 'response.reasoning_text.delta', 'response.reasoning_summary_part.done'):
                delta = '\n\n' if kind.endswith('part.done') else event['delta']
                block['thinking'] += delta
                yield self.event('thinking_delta', offset, delta=delta)
            elif tag == 'text' and kind in ('response.output_text.delta', 'response.refusal.delta'):
                block['text'] += event['delta']
                yield self.event('text_delta', offset, delta=event['delta'])
            elif tag == 'toolcall' and 'partialJson' in block and kind in ('response.function_call_arguments.delta', 'response.function_call_arguments.done'):
                previous = block['partialJson']
                block['partialJson'] = previous + event['delta'] if kind.endswith('.delta') else event['arguments']
                block['arguments'] = parse_streaming_json(block['partialJson'])
                if kind.endswith('.delta') or block['partialJson'].startswith(previous):
                    delta = block['partialJson'][len(previous):]
                    if delta or kind.endswith('.delta'):
                        yield self.event('toolcall_delta', offset, delta=delta)
            elif tag == 'toolcall' and 'customInput' in block and kind in ('response.custom_tool_call_input.delta', 'response.custom_tool_call_input.done'):
                text = block['arguments']['input'] + event['delta'] if kind.endswith('.delta') else event['input']
                delta = self.custom_delta(block, text, kind.endswith('.done'))
                if delta:
                    yield self.event('toolcall_delta', offset, delta=delta)

    def finish(self, signal=None):
        if not self.terminal:
            raise ValueError('OpenAI Responses stream ended before a terminal response event')
        if aborted(signal):
            raise ValueError('Request was aborted')
        if self.output['stopReason'] in ('pending', 'error', 'aborted'):
            raise ValueError(self.output.get('errorMessage') or 'An unknown error occurred')
        yield dict(type='done', reason=self.output['stopReason'], message=self.output)

    def failure(self, error, signal):
        for block in self.output['content']:
            block.pop('partialJson', None)
            block.pop('customInput', None)
        self.output.update(stopReason='aborted' if aborted(signal) else 'error', errorMessage=str(error))
        return dict(type='error', reason=self.output['stopReason'], error=self.output)


def responses_events(model, context, options, signal=None):
    decoder = ResponsesDecoder(model)
    deadline = _HeaderDeadline(signal, options.get('timeoutMs', 600000))
    try:
        payload = build_responses_params(model, context, options, simple=True)
        headers = dict(model.get('headers', {}))
        if model['provider'] == 'github-copilot':
            history = context['messages']
            headers.update({'X-Initiator': 'agent' if history and history[-1]['role'] != 'user' else 'user', 'Openai-Intent': 'conversation-edits'})
            if any(message['role'] in ('user', 'toolResult') and isinstance(message['content'], list) and
                   any(block['type'] == 'image' for block in message['content']) for message in history):
                headers['Copilot-Vision-Request'] = 'true'
        session = options.get('sessionId') if options.get('cacheRetention') != 'none' else None
        if session:
            if model['provider'] == 'openrouter' or 'openrouter.ai' in model['baseUrl']:
                headers['x-session-id'] = session
            else:
                headers.update(session_id=session, **{'x-client-request-id': session})
        headers.update(options.get('headers', {}))
        key = options.get('apiKey')
        if not key and any(name.lower() in ('authorization', 'cf-aig-authorization') and value.strip() for name, value in options.get('headers', {}).items()):
            key = 'unused'
        if not key:
            raise ValueError('No API key for provider: ' + model['provider'])
        if not any(name.lower() == 'authorization' for name in headers):
            headers['Authorization'] = 'Bearer ' + key
        headers.setdefault('Content-Type', 'application/json')
        request = urllib.request.Request(model['baseUrl'].rstrip('/') + '/responses', data=dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with open_stream(request, deadline, options.get('streamIdleTimeoutMs', 300000)) as (_, chunks):
            deadline.enabled = False
            yield decoder.event('start')
            for data in parse_sse(chunks, require_done=False):
                if data == '[DONE]':
                    break
                yield from decoder.feed(loads(data))
        yield from decoder.finish(signal)
    except urllib.error.HTTPError as error:
        body = getattr(error, '_dsh_body', b'').decode('utf-8', errors='replace')
        yield decoder.failure('{} {}'.format(error.code, body or '(no body)'), signal)
    except Exception as error:
        if deadline.timed_out and not aborted(signal):
            error = RuntimeError('Request timed out.')
        elif isinstance(error, (urllib.error.URLError, OSError)):
            error = RuntimeError('Connection error. ' + str(error))
        yield decoder.failure(error, signal)
