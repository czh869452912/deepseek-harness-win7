"""Native Anthropic API-key streaming (pi-ai port, PI_AI_LICENSE.txt)."""
import codecs
import urllib.error
import urllib.request

from dsh.core.cancellation import aborted
from dsh.llm.http_stream import open_stream
from dsh.llm.pi_anthropic_params import build_anthropic_params
from dsh.llm.pi_completions_stream import _HeaderDeadline
from dsh.llm.pi_json import dumps, loads, repair_json, parse_streaming_json
from dsh.llm.pi_replay import empty_usage


def named_sse(chunks):
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    line, data, name, after_cr = '', [], None, False
    for chunk in chunks:
        for char in decoder.decode(chunk):
            if after_cr:
                after_cr = False
                if char == '\n':
                    continue
            if char not in '\r\n':
                line += char
                continue
            after_cr = char == '\r'
            if not line:
                if name is not None or data:
                    yield name, '\n'.join(data)
                data, name = [], None
            elif not line.startswith(':'):
                field, separator, value = line.partition(':')
                value = value[1:] if value.startswith(' ') else value
                if field == 'event':
                    name = value
                elif field == 'data':
                    data.append(value)
            line = ''
    line += decoder.decode(b'', final=True)
    if line:
        field, _, value = line.partition(':')
        value = value[1:] if value.startswith(' ') else value
        if field == 'event':
            name = value
        elif field == 'data':
            data.append(value)
    if name is not None or data:
        yield name, '\n'.join(data)


class AnthropicDecoder:
    def __init__(self, model):
        self.model = model
        self.output = dict(role='assistant', content=[], api=model['api'], provider=model['provider'],
                           model=model['id'], usage=empty_usage(), stopReason='pending', timestamp=0)
        self.slots, self.started, self.ended = {}, False, False

    def event(self, kind, index=None, **data):
        return dict(type=kind, partial=self.output, **({'contentIndex': index} if index is not None else {}), **data)

    def usage(self, raw, initial=False):
        usage = self.output['usage']
        for source, target in [('input_tokens', 'input'), ('output_tokens', 'output'),
                               ('cache_read_input_tokens', 'cacheRead'), ('cache_creation_input_tokens', 'cacheWrite')]:
            if initial or raw.get(source) is not None:
                usage[target] = raw.get(source) or 0
        if initial:
            usage['cacheWrite1h'] = (raw.get('cache_creation') or {}).get('ephemeral_1h_input_tokens') or 0
        elif (raw.get('output_tokens_details') or {}).get('thinking_tokens') is not None:
            usage['reasoning'] = raw['output_tokens_details']['thinking_tokens']
        usage['totalTokens'] = sum(usage[key] for key in ('input', 'output', 'cacheRead', 'cacheWrite'))
        rates = self.model.get('cost', {})
        long_write = usage.get('cacheWrite1h', 0)
        usage['cost'] = {key: usage[key] * rates.get(key, 0) / 1000000 for key in ('input', 'output', 'cacheRead')}
        usage['cost']['cacheWrite'] = ((usage['cacheWrite'] - long_write) * rates.get('cacheWrite', 0) + 2 * long_write * rates.get('input', 0)) / 1000000
        usage['cost']['total'] = sum(usage['cost'].values())

    def feed(self, event):
        kind, index = event.get('type'), event.get('index')
        if kind == 'message_start':
            self.started = True
            self.output['responseId'] = event['message']['id']
            self.usage(event['message']['usage'], True)
        elif kind == 'message_stop':
            self.ended = True
        elif kind == 'content_block_start':
            source = event['content_block']
            tag = source['type']
            if tag == 'text':
                block, prefix = dict(type='text', text=source.get('text') or ''), 'text'
            elif tag == 'thinking':
                block, prefix = dict(type='thinking', thinking=source.get('thinking') or '', thinkingSignature=source.get('signature') or ''), 'thinking'
            elif tag == 'redacted_thinking':
                block, prefix = dict(type='thinking', thinking='[Reasoning redacted]', thinkingSignature=source['data'], redacted=True), 'thinking'
            elif tag == 'tool_use':
                block, prefix = dict(type='toolCall', id=source['id'], name=source['name'], arguments=source.get('input') or {}, partialJson=''), 'toolcall'
            else:
                return
            offset = len(self.output['content'])
            self.output['content'].append(block)
            self.slots[index] = (offset, prefix, block)
            yield self.event(prefix + '_start', offset)
        elif kind == 'content_block_delta' and index in self.slots:
            offset, prefix, block = self.slots[index]
            delta = event['delta']
            if prefix == 'text' and delta['type'] == 'text_delta':
                block['text'] += delta['text']
                yield self.event('text_delta', offset, delta=delta['text'])
            elif prefix == 'thinking' and delta['type'] == 'thinking_delta':
                block['thinking'] += delta['thinking']
                yield self.event('thinking_delta', offset, delta=delta['thinking'])
            elif prefix == 'thinking' and delta['type'] == 'signature_delta':
                block['thinkingSignature'] += delta['signature']
            elif prefix == 'toolcall' and delta['type'] == 'input_json_delta':
                block['partialJson'] += delta['partial_json']
                block['arguments'] = parse_streaming_json(block['partialJson'])
                yield self.event('toolcall_delta', offset, delta=delta['partial_json'])
        elif kind == 'content_block_stop' and index in self.slots:
            offset, prefix, block = self.slots.pop(index)
            if prefix == 'toolcall':
                block['arguments'] = parse_streaming_json(block.pop('partialJson'))
                yield self.event('toolcall_end', offset, toolCall=block)
            else:
                yield self.event(prefix + '_end', offset, content=block['text' if prefix == 'text' else 'thinking'])
        elif kind == 'message_delta':
            delta = event['delta']
            reason = delta.get('stop_reason')
            if reason:
                self.output['rawStopReason'] = reason
                stops = dict(end_turn='stop', max_tokens='length', tool_use='toolUse', pause_turn='stop', stop_sequence='stop')
                if reason in stops:
                    self.output['stopReason'] = stops[reason]
                elif reason in ('refusal', 'sensitive'):
                    self.output['stopReason'] = 'error'
                    self.output['errorMessage'] = ((delta.get('stop_details') or {}).get('explanation') or 'The model refused to complete the request') if reason == 'refusal' else 'Provider stopped with: sensitive'
                else:
                    raise ValueError('Unhandled stop reason: ' + reason)
            self.usage(event.get('usage') or {})

    def finish(self, signal):
        if self.started and not self.ended:
            raise ValueError('Anthropic stream ended before message_stop')
        if aborted(signal):
            raise ValueError('Request was aborted')
        if self.output['stopReason'] == 'pending':
            raise ValueError('Anthropic stream ended without a stop reason')
        if self.output['stopReason'] in ('aborted', 'error'):
            raise ValueError(self.output.get('errorMessage') or 'An unknown error occurred')
        yield dict(type='done', reason=self.output['stopReason'], message=self.output)

    def failure(self, error, signal):
        for block in self.output['content']:
            block.pop('partialJson', None)
        self.output.update(stopReason='aborted' if aborted(signal) else 'error', errorMessage=str(error))
        return dict(type='error', reason=self.output['stopReason'], error=self.output)


def anthropic_events(model, context, options, signal=None):
    decoder = AnthropicDecoder(model)
    deadline = _HeaderDeadline(signal, options.get('timeoutMs', 600000))
    try:
        key = options.get('apiKey')
        if key and 'sk-ant-oat' in key:
            raise ValueError('Anthropic OAuth token transport is not implemented; use an API key')
        payload = build_anthropic_params(model, context, options, simple=True)
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'anthropic-version': '2023-06-01',
                   'anthropic-dangerous-direct-browser-access': 'true'}
        beta = []
        if context.get('tools') and model.get('compat', {}).get('supportsEagerToolInputStreaming') is False:
            beta.append('fine-grained-tool-streaming-2025-05-14')
        if not model.get('compat', {}).get('forceAdaptiveThinking'):
            beta.append('interleaved-thinking-2025-05-14')
        if beta:
            headers['anthropic-beta'] = ','.join(beta)
        if key:
            headers['Authorization' if model['provider'] == 'github-copilot' else 'x-api-key'] = ('Bearer ' if model['provider'] == 'github-copilot' else '') + key
        if options.get('sessionId') and options.get('cacheRetention') != 'none' and model.get('compat', {}).get('sendSessionAffinityHeaders'):
            headers['x-session-affinity'] = options['sessionId']
        headers.update(model.get('headers', {}))
        headers.update(options.get('headers', {}))
        if not key and not any(name.lower() in ('authorization', 'x-api-key', 'cf-aig-authorization') and value.strip() for name, value in options.get('headers', {}).items()):
            raise ValueError('No API key for provider: ' + model['provider'])
        request = urllib.request.Request(model['baseUrl'].rstrip('/') + '/v1/messages', data=dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with open_stream(request, deadline, options.get('streamIdleTimeoutMs', 300000)) as (_, chunks):
            deadline.enabled = False
            yield decoder.event('start')
            accepted = {'message_start', 'message_delta', 'message_stop', 'content_block_start', 'content_block_delta', 'content_block_stop'}
            for name, data in named_sse(chunks):
                if name == 'error':
                    raise ValueError(data)
                if name in accepted:
                    try:
                        event = loads(data)
                    except ValueError:
                        event = loads(repair_json(data))
                    yield from decoder.feed(event)
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
