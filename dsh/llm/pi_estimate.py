"""pi-ai context capacity estimate (not billed token accounting)."""
import json
import math


def _length(text):
    return len(text.encode('utf-16-le', errors='surrogatepass')) // 2


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    except (ValueError, TypeError):
        return '[unserializable]'


def estimate_text_tokens(text):
    return math.ceil(_length(text) / 4)


def estimate_message_tokens(message):
    content = message['content']
    if isinstance(content, str):
        return estimate_text_tokens(content)
    chars = 0
    for block in content:
        if block['type'] == 'text':
            chars += _length(block['text'])
        elif message['role'] in ('user', 'toolResult'):
            chars += 4800
        elif block['type'] == 'thinking':
            chars += _length(block['thinking'])
        else:
            chars += _length(block['name']) + _length(_json(block['arguments']))
    return math.ceil(chars / 4)


def estimate_context_tokens(context):
    history = context if isinstance(context, list) else context['messages']
    latest, usage, usage_index = float('-inf'), 0, None
    for index, message in enumerate(history):
        if message['role'] == 'assistant':
            facts = message['usage']
            count = facts.get('totalTokens') or sum(facts[key] for key in ('input', 'output', 'cacheRead', 'cacheWrite'))
            if message['timestamp'] >= latest and message['stopReason'] not in ('aborted', 'error') and count > 0:
                usage, usage_index = count, index
        latest = max(latest, message['timestamp'])
    trailing = sum(estimate_message_tokens(message) for message in history[usage_index + 1 if usage_index is not None else 0:])
    if not isinstance(context, list):
        tools = context.get('tools', [])
        if usage_index is None:
            trailing += estimate_text_tokens(context.get('systemPrompt', ''))
        else:
            added = {name for message in history[usage_index + 1:] if message['role'] == 'toolResult'
                     for name in message.get('addedToolNames', [])}
            tools = [tool for tool in tools if tool['name'] in added]
        if tools:
            trailing += estimate_text_tokens(_json(tools))
    return dict(tokens=usage + trailing, usageTokens=usage, trailingTokens=trailing, lastUsageIndex=usage_index)


def clamp_max_tokens(model, context, maximum):
    if model['contextWindow'] <= 0:
        return max(1, maximum)
    available = model['contextWindow'] - estimate_context_tokens(context)['tokens'] - 4096
    return min(maximum, max(1, available))
