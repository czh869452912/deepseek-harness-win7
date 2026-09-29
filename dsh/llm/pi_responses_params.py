"""Responses payloads for the Harness pi-ai vocabulary (PI_AI_LICENSE.txt)."""
import copy

from dsh.llm.pi_estimate import clamp_max_tokens
from dsh.llm.pi_responses_messages import convert_responses_messages


def build_responses_params(model, context, options=None, simple=False):
    options = copy.deepcopy(options or {})
    if simple:
        options['maxTokens'] = clamp_max_tokens(model, context, options.get('maxTokens', model['maxTokens']))
        options['reasoningEffort'] = None if options.get('reasoning') == 'off' else options.get('reasoning')
        # These options are absent from pi-ai's buildBaseOptions.
        for key in ('serviceTier', 'toolChoice', 'reasoningSummary'):
            options.pop(key, None)
        sampling = dict(model.get('samplingParams', {}), **options.get('samplingParams', {}))
    else:
        sampling = options.get('samplingParams', {})
    compat = model.get('compat', {})
    retention = options.get('cacheRetention') or ('long' if options.get('env', {}).get('PI_CACHE_RETENTION') == 'long' else 'short')
    result = dict(model=model['id'], input=convert_responses_messages(model, context), stream=True, store=False)
    if retention != 'none' and 'sessionId' in options:
        result['prompt_cache_key'] = options['sessionId'][:64]
    if retention == 'long' and compat.get('supportsLongCacheRetention', True):
        result['prompt_cache_retention'] = '24h'
    if retention == 'none' and compat.get('supportsExplicitPromptCacheMode'):
        result['prompt_cache_options'] = dict(mode='explicit')
    if options.get('maxTokens'):
        result['max_output_tokens'] = max(options['maxTokens'], 16)
    for source, target in [('temperature', 'temperature'), ('serviceTier', 'service_tier'), ('toolChoice', 'tool_choice')]:
        if source in options:
            result[target] = options[source]
    if context.get('tools'):
        result['tools'] = []
        for tool in context['tools']:
            row = dict(type='function', name=tool['name'], parameters=copy.deepcopy(tool['parameters']))
            if 'description' in tool:
                row['description'] = tool['description']
            if compat.get('supportsStrictMode', False):
                row['strict'] = False
            result['tools'].append(row)
    if model.get('reasoning'):
        effort, summary = options.get('reasoningEffort'), options.get('reasoningSummary')
        mapping = model.get('thinkingLevelMap', {})
        if effort or summary:
            result['reasoning'] = dict(effort=(mapping.get(effort) or effort) if effort else 'medium', summary=summary or 'auto')
            result['include'] = ['reasoning.encrypted_content']
        elif model['provider'] != 'github-copilot' and ('off' not in mapping or mapping['off'] is not None):
            result['reasoning'] = dict(effort=mapping.get('off', 'none'))
        if model['provider'] == 'xai':
            result['include'] = ['reasoning.encrypted_content']
    result.update(sampling)
    return result
