"""pi-ai Chat Completions history conversion (see PI_AI_LICENSE.txt)."""
import json
import re

from dsh.llm.pi_transform import transform_messages


def sanitize(text):
    return text.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='ignore')


def _base36(value):
    digits, result = '0123456789abcdefghijklmnopqrstuvwxyz', ''
    while value:
        value, remainder = divmod(value, 36)
        result = digits[remainder] + result
    return result or '0'


def short_hash(text):
    h1, h2 = 0xdeadbeef, 0x41c6ce57
    data = text.encode('utf-16-le', errors='surrogatepass')
    for index in range(0, len(data), 2):
        char = data[index] + data[index + 1] * 256
        h1 = ((h1 ^ char) * 2654435761) & 0xffffffff
        h2 = ((h2 ^ char) * 1597334677) & 0xffffffff
    h1 = (((h1 ^ (h1 >> 16)) * 2246822507) ^ ((h2 ^ (h2 >> 13)) * 3266489909)) & 0xffffffff
    h2 = (((h2 ^ (h2 >> 16)) * 2246822507) ^ ((h1 ^ (h1 >> 13)) * 3266489909)) & 0xffffffff
    return _base36(h2) + _base36(h1)


def normalize_id(identity, model, _message=None):
    if '|' in identity:
        encoded = identity.encode('utf-16-le', errors='surrogatepass')
        units = ''.join(chr(encoded[index] + encoded[index + 1] * 256) for index in range(0, len(encoded), 2))
        call, item = [re.sub('[^a-zA-Z0-9_-]', '_', value) for value in units.split('|', 1)]
        combined = call + '_' + item if item else call
        if len(combined) <= 40:
            return combined
        digest = short_hash(identity)[:8]
        return call[:max(1, 40 - len(digest) - 1)] + '_' + digest
    if model['provider'] == 'openai':
        return identity.encode('utf-16-le', errors='surrogatepass')[:80].decode('utf-16-le', errors='surrogatepass')
    return identity


def _image(block):
    return dict(type='image_url', image_url=dict(url='data:{};base64,{}'.format(block['mimeType'], block['data'])))


def convert_messages(model, context, compat):
    history = transform_messages(context['messages'], model, normalize_id)
    result, last_role, index = [], None, 0

    def bridge():
        result.append(dict(role='assistant', content='I have processed the tool results.'))

    if context.get('systemPrompt'):
        result.append(dict(role='developer' if model.get('reasoning') and compat.get('supportsDeveloperRole') else 'system',
                           content=sanitize(context['systemPrompt'])))
    while index < len(history):
        message = history[index]
        role, content = message['role'], message['content']
        index += 1
        if compat.get('requiresAssistantAfterToolResult') and last_role == 'toolResult' and role == 'user':
            bridge()
        if role == 'user':
            if isinstance(content, str):
                result.append(dict(role='user', content=sanitize(content)))
            elif content:
                result.append(dict(role='user', content=[dict(type='text', text=sanitize(block['text']))
                    if block['type'] == 'text' else _image(block) for block in content]))
            else:
                continue
        elif role == 'assistant':
            row = dict(role='assistant', content='' if compat.get('requiresAssistantAfterToolResult') else None)
            texts = [dict(type='text', text=sanitize(block['text'])) for block in content
                     if block['type'] == 'text' and block['text'].strip()]
            text = ''.join(block['text'] for block in texts)
            thinking = [block for block in content if block['type'] == 'thinking' and block['thinking'].strip()]
            if thinking and compat.get('requiresThinkingAsText'):
                row['content'] = [dict(type='text', text='\n\n'.join(sanitize(block['thinking']) for block in thinking))] + texts
            else:
                if text:
                    row['content'] = text
                if thinking:
                    signature = thinking[0].get('thinkingSignature')
                    if model['provider'] == 'opencode-go' and signature == 'reasoning':
                        signature = 'reasoning_content'
                    if signature:
                        row[signature] = '\n'.join(block['thinking'] for block in thinking)
            calls = [block for block in content if block['type'] == 'toolCall']
            if calls:
                row['tool_calls'] = [dict(id=call['id'], type='function', function=dict(name=call['name'],
                    arguments=json.dumps(call['arguments'], ensure_ascii=False, separators=(',', ':')))) for call in calls]
                details = []
                for call in calls:
                    if call.get('thoughtSignature'):
                        try:
                            detail = json.loads(call['thoughtSignature'])
                        except ValueError:
                            continue
                        if detail is not None and detail is not False and detail != '' and detail != 0:
                            details.append(detail)
                if details:
                    row['reasoning_details'] = details
            if compat.get('requiresReasoningContentOnAssistantMessages') and model.get('reasoning'):
                row.setdefault('reasoning_content', '')
            if not row['content'] and not row.get('tool_calls'):
                continue
            result.append(row)
        elif role == 'toolResult':
            attachments = []
            while True:
                text = '\n'.join(block['text'] for block in content if block['type'] == 'text')
                has_images = any(block['type'] == 'image' for block in content)
                row = dict(role='tool', content=sanitize(text or ('(see attached image)' if has_images else '(no tool output)')),
                           tool_call_id=message['toolCallId'])
                if compat.get('requiresToolResultName') and message.get('toolName'):
                    row['name'] = message['toolName']
                result.append(row)
                if has_images and 'image' in model['input']:
                    attachments.extend(_image(block) for block in content if block['type'] == 'image')
                if index == len(history) or history[index]['role'] != 'toolResult':
                    break
                message = history[index]
                content = message['content']
                index += 1
            if attachments:
                if compat.get('requiresAssistantAfterToolResult'):
                    bridge()
                result.append(dict(role='user', content=[dict(type='text', text='Attached image(s) from tool result:')] + attachments))
                last_role = 'user'
            else:
                last_role = 'toolResult'
            continue
        last_role = role
    return result
