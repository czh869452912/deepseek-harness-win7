"""Loopback model fixtures speak the protocol selected by the actual request."""
import json


def sse_events(events):
    return ''.join('event: ' + event['type'] + '\ndata: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
                   for event in events).encode('utf-8')


def model_sse(path, delta, finish='stop', complete=True):
    if not path.rstrip('/').endswith('/messages'):
        chunk = dict(choices=[dict(delta=delta, finish_reason=finish)])
        return ('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n' +
                ('data: [DONE]\n\n' if complete else '')).encode('utf-8')
    events = [dict(type='message_start', message=dict(usage=dict(input_tokens=10, output_tokens=0)))]
    blocks = []
    if delta.get('reasoning_content'):
        blocks.append((dict(type='thinking', thinking=''), dict(type='thinking_delta', thinking=delta['reasoning_content'])))
    if delta.get('content'):
        blocks.append((dict(type='text', text=''), dict(type='text_delta', text=delta['content'])))
    for call in delta.get('tool_calls', []):
        function = call['function']
        blocks.append((dict(type='tool_use', id=call['id'], name=function['name'], input={}),
                       dict(type='input_json_delta', partial_json=function['arguments'])))
    for index, (block, update) in enumerate(blocks):
        events.extend([dict(type='content_block_start', index=index, content_block=block),
                       dict(type='content_block_delta', index=index, delta=update)])
        if complete or index < len(blocks) - 1:
            events.append(dict(type='content_block_stop', index=index))
    if complete:
        events.extend([dict(type='message_delta', delta=dict(stop_reason='tool_use' if finish == 'tool_calls' else 'end_turn'),
                            usage=dict(output_tokens=2)), dict(type='message_stop')])
    return sse_events(events)


def model_finish(path):
    if not path.rstrip('/').endswith('/messages'):
        return b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    return sse_events([dict(type='content_block_stop', index=0),
                       dict(type='message_delta', delta=dict(stop_reason='end_turn'), usage=dict(output_tokens=2)),
                       dict(type='message_stop')])
