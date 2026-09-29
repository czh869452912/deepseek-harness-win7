"""Anthropic API-key request vocabulary from pi-ai (PI_AI_LICENSE.txt)."""
import copy
import re

from dsh.llm.pi_completions_messages import sanitize
from dsh.llm.pi_estimate import clamp_max_tokens
from dsh.llm.pi_transform import transform_messages


def _image(block):
    return dict(type='image', source=dict(type='base64', media_type=block['mimeType'], data=block['data']))


def _normalize_id(identity, _model, _source):
    raw = identity.encode('utf-16-le', errors='surrogatepass')
    units = ''.join(chr(raw[index] + raw[index + 1] * 256) for index in range(0, len(raw), 2))
    return re.sub('[^a-zA-Z0-9_-]', '_', units)[:64]


def convert_anthropic_messages(model, context, cache=None):
    history = transform_messages(context['messages'], model, _normalize_id)
    result, index = [], 0
    allow_empty = model.get('compat', {}).get('allowEmptySignature', False)
    while index < len(history):
        message = history[index]
        index += 1
        role, content = message['role'], message['content']
        if role == 'user':
            if isinstance(content, str):
                blocks = sanitize(content) if content.strip() else None
            else:
                blocks = [dict(type='text', text=sanitize(block['text'])) if block['type'] == 'text' else _image(block)
                          for block in content if block['type'] != 'text' or block['text'].strip()]
            if blocks:
                result.append(dict(role='user', content=blocks))
        elif role == 'assistant':
            blocks = []
            for block in content:
                kind = block['type']
                if kind == 'text' and block['text'].strip():
                    blocks.append(dict(type='text', text=sanitize(block['text'])))
                elif kind == 'thinking':
                    signature = block.get('thinkingSignature')
                    if block.get('redacted'):
                        row = dict(type='redacted_thinking')
                        if signature is not None:
                            row['data'] = signature
                        blocks.append(row)
                    elif block.get('thinking', '').strip() or (signature and signature.strip()):
                        if allow_empty or signature and signature.strip():
                            blocks.append(dict(type='thinking', thinking=sanitize(block['thinking']), signature=signature if signature and signature.strip() else ''))
                        else:
                            blocks.append(dict(type='text', text=sanitize(block['thinking'])))
                elif kind == 'toolCall':
                    blocks.append(dict(type='tool_use', id=block['id'], name=block['name'], input=block.get('arguments') or {}))
            if blocks:
                result.append(dict(role='assistant', content=blocks))
        elif role == 'toolResult':
            messages = [message]
            while index < len(history) and history[index]['role'] == 'toolResult':
                messages.append(history[index])
                index += 1
            results = []
            for item in messages:
                content = item['content']
                if any(block['type'] == 'image' for block in content):
                    converted = [dict(type='text', text=sanitize(block['text'])) if block['type'] == 'text' else _image(block) for block in content]
                    if not any(block['type'] == 'text' for block in content):
                        converted.insert(0, dict(type='text', text='(see attached image)'))
                else:
                    converted = sanitize('\n'.join(block['text'] for block in content))
                results.append(dict(type='tool_result', tool_use_id=item['toolCallId'], content=converted, is_error=item['isError']))
            result.append(dict(role='user', content=results))
    if cache and result and result[-1]['role'] == 'user':
        content = result[-1]['content']
        if isinstance(content, str):
            result[-1]['content'] = [dict(type='text', text=content, cache_control=cache)]
        elif content and content[-1]['type'] in ('text', 'image', 'tool_result'):
            content[-1]['cache_control'] = cache
    return result


def build_anthropic_params(model, context, options=None, simple=False):
    options = copy.deepcopy(options or {})
    compat = model.get('compat', {})
    if simple:
        maximum = clamp_max_tokens(model, context, options.get('maxTokens', model['maxTokens']))
        level = options.get('reasoning')
        options['thinkingEnabled'] = bool(level)
        if level and compat.get('forceAdaptiveThinking'):
            options['effort'] = model.get('thinkingLevelMap', {}).get(level) or ('low' if level in ('minimal', 'low') else 'medium' if level == 'medium' else 'high')
        elif level:
            budgets = dict(minimal=1024, low=2048, medium=8192, high=16384, **{})
            budgets.update(options.get('thinkingBudgets', {}))
            budget = budgets.get('high' if level in ('xhigh', 'max') else level, 0)
            maximum = min(maximum + budget, model['maxTokens'])
            if maximum <= budget:
                budget = max(0, maximum - 1024)
            maximum = clamp_max_tokens(model, context, maximum)
            options['thinkingBudgetTokens'] = min(budget, max(0, maximum - 1024))
        options['maxTokens'] = maximum
        options.pop('thinkingDisplay', None)
        options.pop('toolChoice', None)
    retention = options.get('cacheRetention') or ('long' if options.get('env', {}).get('PI_CACHE_RETENTION') == 'long' else 'short')
    cache = None if retention == 'none' else dict(type='ephemeral', **({'ttl': '1h'} if retention == 'long' and compat.get('supportsLongCacheRetention', True) else {}))
    result = dict(model=model['id'], messages=convert_anthropic_messages(model, context, cache),
                  max_tokens=options.get('maxTokens', model['maxTokens']), stream=True)
    if context.get('systemPrompt'):
        result['system'] = [dict(type='text', text=sanitize(context['systemPrompt']), **({'cache_control': cache} if cache else {}))]
    if 'temperature' in options and not options.get('thinkingEnabled') and compat.get('supportsTemperature', True):
        result['temperature'] = options['temperature']
    if context.get('tools'):
        result['tools'] = []
        for tool in context['tools']:
            schema = tool['parameters']
            row = dict(name=tool['name'], input_schema=dict(type='object', properties=schema.get('properties', {}), required=schema.get('required', [])))
            if 'description' in tool:
                row['description'] = tool['description']
            if compat.get('supportsEagerToolInputStreaming', True):
                row['eager_input_streaming'] = True
            result['tools'].append(row)
        if cache and compat.get('supportsCacheControlOnTools', True):
            result['tools'][-1]['cache_control'] = cache
    if model.get('reasoning'):
        if options.get('thinkingEnabled'):
            display = options.get('thinkingDisplay', 'summarized')
            if compat.get('forceAdaptiveThinking'):
                result['thinking'] = dict(type='adaptive', display=display)
                if options.get('effort'):
                    result['output_config'] = dict(effort=options['effort'])
            else:
                result['thinking'] = dict(type='enabled', budget_tokens=options.get('thinkingBudgetTokens') or 1024, display=display)
        elif options.get('thinkingEnabled') is False and ('off' not in model.get('thinkingLevelMap', {}) or model['thinkingLevelMap']['off'] is not None):
            result['thinking'] = dict(type='disabled')
    if isinstance(options.get('metadata', {}).get('user_id'), str):
        result['metadata'] = dict(user_id=options['metadata']['user_id'])
    if options.get('toolChoice'):
        choice = options['toolChoice']
        result['tool_choice'] = dict(type=choice) if isinstance(choice, str) else choice
    return result
