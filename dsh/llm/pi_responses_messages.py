"""Responses history conversion from pinned pi-ai (see PI_AI_LICENSE.txt)."""
import re

from dsh.llm.pi_completions_messages import sanitize, short_hash
from dsh.llm.pi_json import dumps, loads
from dsh.llm.pi_transform import transform_messages

ALLOWED_TOOL_PROVIDERS = {'openai', 'openai-codex', 'opencode'}


def text_signature(signature):
    if not signature:
        return None
    if signature.startswith('{'):
        try:
            parsed = loads(signature)
            if parsed.get('v') == 1 and isinstance(parsed.get('id'), str):
                return dict(id=parsed['id'], **({'phase': parsed['phase']}
                    if parsed.get('phase') in ('commentary', 'final_answer') else {}))
        except (ValueError, TypeError, AttributeError):
            pass
    return dict(id=signature)


def _normalize_part(part):
    encoded = part.encode('utf-16-le', errors='surrogatepass')
    units = ''.join(chr(encoded[index] + encoded[index + 1] * 256) for index in range(0, len(encoded), 2))
    return re.sub('[^a-zA-Z0-9_-]', '_', units)[:64].rstrip('_')


def _image(block):
    return dict(type='input_image', detail='auto', image_url='data:{};base64,{}'.format(block['mimeType'], block['data']))


def convert_responses_messages(model, context, allowed=None, options=None):
    allowed = ALLOWED_TOOL_PROVIDERS if allowed is None else allowed
    options = options or {}

    def normalize(identity, target, source):
        if target['provider'] not in allowed or '|' not in identity:
            return _normalize_part(identity)
        call, item = identity.split('|')[:2]
        foreign = source['provider'] != target['provider'] or source['api'] != target['api']
        item = 'fc_' + short_hash(item) if foreign else _normalize_part(item)
        if not item.startswith('fc_'):
            item = _normalize_part('fc_' + item)
        return _normalize_part(call) + '|' + item

    history = transform_messages(context['messages'], model, normalize)
    result = []
    if options.get('includeSystemPrompt', True) and context.get('systemPrompt'):
        role = 'developer' if model.get('reasoning') and model.get('compat', {}).get('supportsDeveloperRole') is not False else 'system'
        result.append(dict(role=role, content=sanitize(context['systemPrompt'])))
    index = 0
    for message in history:
        role, content = message['role'], message['content']
        if role == 'user':
            blocks = [dict(type='input_text', text=sanitize(content))] if isinstance(content, str) else [
                dict(type='input_text', text=sanitize(block['text'])) if block['type'] == 'text' else _image(block) for block in content]
            if not blocks:
                continue
            result.append(dict(role='user', content=blocks))
        elif role == 'assistant':
            same_provider = message['provider'] == model['provider'] and message['api'] == model['api']
            same_model = same_provider and message['model'] == model['id']
            output, text_index = [], 0
            for block in content:
                kind = block['type']
                if kind == 'thinking' and block.get('thinkingSignature'):
                    output.append(loads(block['thinkingSignature']))
                elif kind == 'text':
                    signature = text_signature(block.get('textSignature')) or {}
                    identity = signature.get('id') or ('msg_pi_{}'.format(index) if text_index == 0 else 'msg_pi_{}_{}'.format(index, text_index))
                    text_index += 1
                    if len(identity.encode('utf-16-le', errors='surrogatepass')) > 128:
                        identity = 'msg_' + short_hash(identity)
                    row = dict(type='message', role='assistant', content=[dict(type='output_text', text=sanitize(block['text']), annotations=[])],
                               status='completed', id=identity)
                    if 'phase' in signature:
                        row['phase'] = signature['phase']
                    output.append(row)
                elif kind == 'toolCall':
                    parts = block['id'].split('|')
                    row = dict(type='function_call', call_id=parts[0], name=block['name'], arguments=dumps(block['arguments']))
                    if len(parts) > 1 and parts[1].startswith('fc_') and not (same_provider and not same_model):
                        row['id'] = parts[1]
                    if same_model and 'namespace' in block:
                        row['namespace'] = block['namespace']
                    output.append(row)
            if not output:
                continue
            result.extend(output)
        elif role == 'toolResult':
            text = '\n'.join(block['text'] for block in content if block['type'] == 'text')
            images = [block for block in content if block['type'] == 'image']
            if not images or 'image' not in model['input']:
                output = sanitize(text or ('(see attached image)' if images else '(no tool output)'))
            else:
                output = ([dict(type='input_text', text=sanitize(text))] if text else []) + [_image(block) for block in images]
            result.append(dict(type='function_call_output', call_id=message['toolCallId'].split('|')[0], output=output))
        index += 1
    return result
