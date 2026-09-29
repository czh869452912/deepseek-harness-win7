"""Model capability descriptions and strict reasoning selection."""
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_catalog import THINKING_LEVELS


def supported_thinking_levels(model):
    if not model.get('reasoning'):
        return ['off']
    mapping = model.get('thinkingLevelMap', {})
    return [level for level in THINKING_LEVELS if
            (level not in mapping or mapping[level] is not None) and
            (level not in ('xhigh', 'max') or level in mapping)]


def resolve_reasoning_level(model, effort):
    if effort is not None and effort not in supported_thinking_levels(model):
        raise LlmError('pi-ai provider "{}" model "{}" does not support reasoning effort "{}"'.format(
            model['provider'], model['id'], effort), 'UNSUPPORTED_REASONING_EFFORT')
    return effort


def model_info(profile, identity):
    model = next((row for row in profile['models'] if row['id'] == identity), None)
    if model is None:
        raise LlmError('pi-ai provider "{}" has no configured model "{}"'.format(profile['provider'], identity), 'UNKNOWN_MODEL')
    result = dict(provider=profile['provider'], id=identity, name=model['name'],
                  inputModalities=list(model['input']), context=dict(contextWindow=model['contextWindow']))
    if identity in profile['configuredMaxTokens']:
        result['defaultMaxTokens'] = profile['configuredMaxTokens'][identity]
    if model.get('reasoning'):
        levels = supported_thinking_levels(model)
        result['reasoning'] = dict(efforts=[dict(id=level, name=level.capitalize()) for level in levels])
        if profile.get('reasoning') in levels:
            result['reasoning']['defaultEffort'] = profile['reasoning']
    return result
