"""Cross-model history normalization adapted from pi-ai 0.84.2 (PI_AI_LICENSE.txt)."""
import copy
import time


def _downgrade(content, placeholder):
    result, previous = [], False
    for block in content:
        if block['type'] == 'image':
            if not previous:
                result.append(dict(type='text', text=placeholder))
            previous = True
        else:
            result.append(block)
            previous = block.get('text') == placeholder
    return result


def transform_messages(messages, model, normalize_tool_call_id=None, now=None):
    now = now or (lambda: int(time.time() * 1000))
    messages = copy.deepcopy(messages)
    mapping, transformed = {}, []
    for message in messages:
        if message.get('content') is None:
            message['content'] = []
        role, content = message['role'], message['content']
        if 'image' not in model['input']:
            if role == 'user' and isinstance(content, list):
                message['content'] = _downgrade(content, '(image omitted: model does not support images)')
            elif role == 'toolResult':
                message['content'] = _downgrade(content, '(tool image omitted: model does not support images)')
        if role == 'toolResult':
            message['toolCallId'] = mapping.get(message['toolCallId'], message['toolCallId'])
        elif role == 'assistant':
            same = all(message.get(key) == model.get(target) for key, target in
                       [('provider', 'provider'), ('api', 'api'), ('model', 'id')])
            blocks = []
            for block in content:
                kind = block['type']
                if kind == 'thinking':
                    if block.get('redacted'):
                        if same:
                            blocks.append(block)
                        continue
                    if same and block.get('thinkingSignature'):
                        blocks.append(block)
                        continue
                    if not block.get('thinking', '').strip():
                        continue
                    if not same:
                        block = dict(type='text', text=block['thinking'])
                elif kind == 'text' and not same:
                    block = dict(type='text', text=block['text'])
                elif kind == 'toolCall' and not same:
                    block.pop('thoughtSignature', None)
                    if normalize_tool_call_id is not None:
                        original = block['id']
                        normalized = normalize_tool_call_id(original, model, message)
                        if normalized != original:
                            mapping[original] = normalized
                            block['id'] = normalized
                blocks.append(block)
            message['content'] = blocks
        transformed.append(message)

    result, pending, existing = [], [], set()

    def flush():
        for call in pending:
            if call['id'] not in existing:
                result.append(dict(role='toolResult', toolCallId=call['id'], toolName=call['name'],
                    content=[dict(type='text', text='No result provided')], isError=True, timestamp=now()))
        pending.clear()
        existing.clear()

    for message in transformed:
        role = message['role']
        if role == 'assistant':
            flush()
            if message.get('stopReason') in ('error', 'aborted'):
                continue
            pending.extend(block for block in message['content'] if block['type'] == 'toolCall')
        elif role == 'toolResult':
            existing.add(message['toolCallId'])
        elif role == 'user':
            flush()
        result.append(message)
    flush()
    return result
