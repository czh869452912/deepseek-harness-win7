"""Chat Completions payloads for the Harness pi-ai request vocabulary."""
import copy

from dsh.llm.pi_completions_compat import get_compat
from dsh.llm.pi_completions_messages import convert_messages
from dsh.llm.pi_estimate import clamp_max_tokens


def _template(values, effort, mapping):
    result = {}
    for key, value in values.items():
        if isinstance(value, dict):
            if not effort and value.get('omitWhenOff'):
                continue
            value = bool(effort) if value.get('$var') == 'thinking.enabled' else mapping.get(effort or 'off', effort)
            if value is None:
                continue
        result[key] = value
    return result


def _cache_text(message, cache):
    content = message.get('content')
    if isinstance(content, str):
        if not content:
            return False
        message['content'] = [dict(type='text', text=content, cache_control=cache)]
        return True
    if isinstance(content, list):
        for block in reversed(content):
            if block['type'] == 'text':
                block['cache_control'] = cache
                return True
    return False


def build_params(model, context, options=None, simple=False):
    options = copy.deepcopy(options or {})
    if simple:
        options['maxTokens'] = clamp_max_tokens(model, context, options.get('maxTokens', model['maxTokens']))
        effort = options.get('reasoning')
        options['reasoningEffort'] = None if effort == 'off' else effort
    compat = get_compat(model)
    retention = options.get('cacheRetention') or ('long' if options.get('env', {}).get('PI_CACHE_RETENTION') == 'long' else 'short')
    result = dict(model=model['id'], messages=convert_messages(model, context, compat), stream=True)
    if (('api.openai.com' in model['baseUrl'] and retention != 'none') or
            (retention == 'long' and compat['supportsLongCacheRetention'])) and 'sessionId' in options:
        result['prompt_cache_key'] = options['sessionId'][:64]
    if retention == 'long' and compat['supportsLongCacheRetention']:
        result['prompt_cache_retention'] = '24h'
    if compat['supportsUsageInStreaming']:
        result['stream_options'] = dict(include_usage=True)
    if compat['supportsStore']:
        result['store'] = False
    if options.get('maxTokens'):
        result[compat['maxTokensField']] = options['maxTokens']
    if 'temperature' in options:
        result['temperature'] = options['temperature']
    if context.get('tools'):
        result['tools'] = []
        for tool in context['tools']:
            function = {key: copy.deepcopy(tool[key]) for key in ('name', 'description', 'parameters')}
            if compat['supportsStrictMode']:
                function['strict'] = False
            result['tools'].append(dict(type='function', function=function))
        if compat['zaiToolStream']:
            result['tool_stream'] = True
    elif any(message['role'] == 'toolResult' or (message['role'] == 'assistant' and
             any(block['type'] == 'toolCall' for block in message['content'])) for message in context['messages']):
        result['tools'] = []
    if compat.get('cacheControlFormat') == 'anthropic' and retention != 'none':
        cache = dict(type='ephemeral')
        if retention == 'long' and compat['supportsLongCacheRetention']:
            cache['ttl'] = '1h'
        for message in result['messages']:
            if message['role'] in ('system', 'developer'):
                _cache_text(message, cache)
                break
        if result.get('tools'):
            result['tools'][-1]['cache_control'] = cache
        for message in reversed(result['messages']):
            if message['role'] in ('user', 'assistant', 'tool') and _cache_text(message, cache):
                break
    if options.get('toolChoice'):
        result['tool_choice'] = options['toolChoice']
    effort, mapping = options.get('reasoningEffort'), model.get('thinkingLevelMap', {})
    wire = mapping.get(effort, effort)
    off = mapping.get('off')
    off_supported = 'off' not in mapping or off is not None
    if model.get('reasoning'):
        form = compat['thinkingFormat']
        supports = compat['supportsReasoningEffort']
        if form == 'zai':
            result['thinking'] = dict(type='enabled', clear_thinking=False) if effort else dict(type='disabled')
            if effort and supports and isinstance(wire, str):
                result['reasoning_effort'] = wire
        elif form == 'qwen':
            result['enable_thinking'] = bool(effort)
            if effort and supports:
                result['reasoning_effort'] = wire if wire is not None else effort
        elif form == 'qwen-chat-template':
            result['chat_template_kwargs'] = dict(enable_thinking=bool(effort), preserve_thinking=True)
        elif form == 'chat-template':
            values = _template(compat['chatTemplateKwargs'], effort, mapping)
            if values:
                result['chat_template_kwargs'] = values
        elif form == 'baseten':
            values = _template(compat['chatTemplateArgs'], effort, mapping)
            if values:
                result['chat_template_args'] = values
            chosen = wire if effort else off
            if supports and isinstance(chosen, str):
                result['reasoning_effort'] = chosen
        elif form == 'deepseek':
            if effort or off_supported:
                result['thinking'] = dict(type='enabled' if effort else 'disabled')
            if effort and supports:
                result['reasoning_effort'] = wire if wire is not None else effort
        elif form == 'openrouter':
            if effort or off_supported:
                result['reasoning'] = dict(effort=(wire if wire is not None else effort) if effort else (off or 'none'))
        elif form == 'ant-ling' and effort:
            if isinstance(mapping.get(effort), str):
                result['reasoning'] = dict(effort=mapping[effort])
        elif form == 'together':
            result['reasoning'] = dict(enabled=bool(effort))
            if effort and supports:
                result['reasoning_effort'] = wire if wire is not None else effort
        elif form == 'string-thinking':
            if effort or off_supported:
                result['thinking'] = (wire if wire is not None else effort) if effort else (off or 'none')
        elif supports and (effort or isinstance(off, str)):
            result['reasoning_effort'] = (wire if wire is not None else effort) if effort else off
        if compat['supportsThinkingTokenBudget'] and effort:
            budgets = dict(minimal=1024, low=2048, medium=8192, high=16384)
            budgets.update(options.get('thinkingBudgets', {}))
            ceiling = options.get('maxTokens', model['maxTokens'])
            budget = min(budgets['high' if effort in ('xhigh', 'max') else effort], max(0, ceiling - 1024))
            if budget > 0:
                result['thinking_token_budget'] = budget
    if compat.get('openRouterRouting'):
        result['provider'] = copy.deepcopy(compat['openRouterRouting'])
    routing = compat.get('vercelGatewayRouting', {})
    if routing.get('only') or routing.get('order'):
        result['providerOptions'] = dict(gateway={key: routing[key] for key in ('only', 'order') if key in routing})
    sampling = dict(model.get('samplingParams', {}) if simple else {})
    sampling.update(options.get('samplingParams', {}))
    result.update(sampling)
    return result
