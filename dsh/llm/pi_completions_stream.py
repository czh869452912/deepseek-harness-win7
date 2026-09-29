"""Native Chat Completions SSE to pi-ai events with owned HTTP cancellation."""
import urllib.error
import urllib.request
import time

from dsh.core.cancellation import aborted
from dsh.llm.deepseek_wire import parse_sse
from dsh.llm.http_stream import open_stream
from dsh.llm.pi_completions_compat import get_compat
from dsh.llm.pi_completions_params import build_params
from dsh.llm.pi_json import dumps, loads, parse_streaming_json
from dsh.llm.pi_replay import empty_usage


class _HeaderDeadline:
    def __init__(self, caller, timeout_ms):
        self.caller, self.enabled = caller, True
        self.deadline = time.monotonic() + timeout_ms / 1000

    @property
    def timed_out(self):
        return self.enabled and time.monotonic() >= self.deadline

    @property
    def aborted(self):
        return aborted(self.caller) or self.timed_out


class CompletionsDecoder:
    def __init__(self, model):
        self.model, self.compat = model, get_compat(model)
        self.output = dict(role='assistant', content=[], api=model['api'], provider=model['provider'],
                           model=model['id'], usage=empty_usage(), stopReason='pending', timestamp=0)
        self.text, self.thinking, self.finished = None, None, False
        self.indices, self.identities, self.pending, self.arguments, self.custom = {}, {}, {}, {}, {}

    def event(self, kind, index=None, **data):
        event = dict(type=kind, partial=self.output, **data)
        if index is not None:
            event['contentIndex'] = index
        return event

    def usage(self, raw):
        details = raw.get('prompt_tokens_details') or {}
        cached = details.get('cached_tokens', raw.get('prompt_cache_hit_tokens', 0)) or 0
        writes = details.get('cache_write_tokens') or 0
        usage = dict(input=max(0, (raw.get('prompt_tokens') or 0) - cached - writes),
                     output=raw.get('completion_tokens') or 0, cacheRead=cached, cacheWrite=writes,
                     reasoning=(raw.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0)
        usage['totalTokens'] = sum(usage[key] for key in ('input', 'output', 'cacheRead', 'cacheWrite'))
        usage['cost'] = {key: usage[key] * self.model.get('cost', {}).get(key, 0) / 1000000
                         for key in ('input', 'output', 'cacheRead', 'cacheWrite')}
        usage['cost']['total'] = sum(usage['cost'].values())
        self.output['usage'] = usage

    def feed(self, chunk):
        if not isinstance(chunk, dict):
            return
        output, blocks = self.output, self.output['content']
        if not output.get('responseId') and chunk.get('id'):
            output['responseId'] = chunk['id']
        response_model = chunk.get('model')
        if isinstance(response_model, str) and response_model and response_model != self.model['id']:
            output.setdefault('responseModel', response_model)
        if chunk.get('usage'):
            self.usage(chunk['usage'])
        choices = chunk.get('choices')
        if not isinstance(choices, list) or not choices:
            return
        choice = choices[0]
        if not chunk.get('usage') and choice.get('usage'):
            self.usage(choice['usage'])
        reason = choice.get('finish_reason')
        if reason:
            self.finished = True
            output['rawStopReason'] = reason
            output['stopReason'] = {'stop': 'stop', 'end': 'stop', 'length': 'length',
                                    'function_call': 'toolUse', 'tool_calls': 'toolUse'}.get(reason, 'error')
            if output['stopReason'] == 'error':
                output['errorMessage'] = 'Provider finish_reason: ' + str(reason)
        delta = choice.get('delta') or {}
        if delta.get('content'):
            if self.text is None:
                self.text = len(blocks)
                blocks.append(dict(type='text', text=''))
                yield self.event('text_start', self.text)
            blocks[self.text]['text'] += delta['content']
            yield self.event('text_delta', self.text, delta=delta['content'])
        field = next((key for key in ('reasoning_content', 'reasoning', 'reasoning_text')
                      if isinstance(delta.get(key), str) and delta[key]), None)
        if field:
            if self.thinking is None:
                self.thinking = len(blocks)
                signature = 'reasoning_content' if self.model['provider'] == 'opencode-go' and field == 'reasoning' else field
                blocks.append(dict(type='thinking', thinking='', thinkingSignature=signature))
                yield self.event('thinking_start', self.thinking)
            blocks[self.thinking]['thinking'] += delta[field]
            yield self.event('thinking_delta', self.thinking, delta=delta[field])
        for call in delta.get('tool_calls') or []:
            position, identity = call.get('index'), call.get('id')
            function, custom = call.get('function') or {}, call.get('custom') or {}
            name = function.get('name', custom.get('name', ''))
            index = self.indices.get(position) if type(position) in (int, float) else None
            if index is None and identity:
                index = self.identities.get(identity)
            if index is None:
                index = len(blocks)
                blocks.append(dict(type='toolCall', id=identity or '', name=name, arguments={}))
                self.arguments[index] = ''
                yield self.event('toolcall_start', index)
            block = blocks[index]
            if type(position) in (int, float):
                self.indices.setdefault(position, index)
            if identity:
                self.identities[identity] = index
                if not block['id']:
                    block['id'] = identity
            if not block['name'] and name:
                block['name'] = name
            if block['id'] in self.pending:
                block['thoughtSignature'] = self.pending.pop(block['id'])
            change = ''
            if function.get('arguments'):
                change = function['arguments']
                self.arguments[index] += change
                block['arguments'] = parse_streaming_json(self.arguments[index])
            elif custom.get('input'):
                state = self.custom.setdefault(index, dict(started=False, text=''))
                change = ('' if state['started'] else '{"input":"') + dumps(custom['input'])[1:-1]
                state['started'] = True
                state['text'] += custom['input']
                block['arguments'] = dict(input=state['text'])
            elif custom and not function:
                self.custom.setdefault(index, dict(started=False, text=''))
                block['arguments'] = dict(input='')
            yield self.event('toolcall_delta', index, delta=change)
        for detail in delta.get('reasoning_details') or []:
            if (isinstance(detail, dict) and detail.get('type') == 'reasoning.encrypted' and
                    isinstance(detail.get('id'), str) and detail['id'] and isinstance(detail.get('data'), str) and detail['data']):
                if detail['id'] in self.identities:
                    blocks[self.identities[detail['id']]]['thoughtSignature'] = dumps(detail)
                else:
                    self.pending[detail['id']] = dumps(detail)

    def finish(self, signal=None):
        for index, block in enumerate(self.output['content']):
            if block['type'] in ('text', 'thinking'):
                yield self.event(block['type'] + '_end', index, content=block[block['type']])
            else:
                if index in self.custom:
                    yield self.event('toolcall_delta', index, delta=('' if self.custom[index]['started'] else '{"input":"') + '"}')
                else:
                    block['arguments'] = parse_streaming_json(self.arguments[index])
                yield self.event('toolcall_end', index, toolCall=block)
        if aborted(signal):
            raise RuntimeError('Request was aborted')
        if not self.finished and not self.compat['supportsFinishReason']:
            self.output['stopReason'] = 'toolUse' if any(block['type'] == 'toolCall' for block in self.output['content']) else 'stop'
        if self.output['stopReason'] == 'error':
            raise RuntimeError(self.output.get('errorMessage', 'Provider returned an error stop reason'))
        if (self.compat['supportsFinishReason'] and not self.finished) or self.output['stopReason'] == 'pending':
            raise RuntimeError('Stream ended without finish_reason')
        yield dict(type='done', reason=self.output['stopReason'], message=self.output)

    def failure(self, error, signal=None):
        self.output['stopReason'] = 'aborted' if aborted(signal) else 'error'
        self.output['errorMessage'] = str(error)
        return dict(type='error', reason=self.output['stopReason'], error=self.output)


def completions_events(model, context, options, signal=None):
    decoder = CompletionsDecoder(model)
    deadline = _HeaderDeadline(signal, options.get('timeoutMs', 600000))
    try:
        payload = build_params(model, context, options, simple=True)
        headers = dict(model.get('headers', {}))
        if model['provider'] == 'github-copilot':
            messages = context['messages']
            headers.update({'X-Initiator': 'agent' if messages and messages[-1]['role'] != 'user' else 'user',
                            'Openai-Intent': 'conversation-edits'})
            if any(message['role'] in ('user', 'toolResult') and isinstance(message['content'], list) and
                   any(block['type'] == 'image' for block in message['content']) for message in messages):
                headers['Copilot-Vision-Request'] = 'true'
        session = options.get('sessionId') if options.get('cacheRetention') != 'none' else None
        if session and decoder.compat['sendSessionAffinityHeaders']:
            form = decoder.compat['sessionAffinityFormat']
            if form == 'openrouter':
                headers['x-session-id'] = session
            else:
                if form == 'openai':
                    headers['session_id'] = session
                headers.update({'x-client-request-id': session, 'x-session-affinity': session})
        headers.update(options.get('headers', {}))
        key = options.get('apiKey')
        if not key and any(name.lower() in ('authorization', 'cf-aig-authorization') and value.strip()
                           for name, value in options.get('headers', {}).items()):
            key = 'unused'
        if not key:
            raise ValueError('No API key for provider: ' + model['provider'])
        if not any(name.lower() == 'authorization' for name in headers):
            headers['Authorization'] = 'Bearer ' + key
        headers.setdefault('Content-Type', 'application/json')
        request = urllib.request.Request(model['baseUrl'].rstrip('/') + '/chat/completions',
            data=dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with open_stream(request, deadline, options.get('streamIdleTimeoutMs', 300000)) as (_, chunks):
            deadline.enabled = False
            yield decoder.event('start')
            for data in parse_sse(chunks, require_done=False):
                if data == '[DONE]':
                    break
                chunk = loads(data)
                if isinstance(chunk, dict) and chunk.get('error'):
                    raise RuntimeError(dumps(chunk['error']))
                yield from decoder.feed(chunk)
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
