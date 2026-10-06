import math


def _integer(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value == math.trunc(value)


def _nonempty_string(value):
    return isinstance(value, str) and len(value) > 0


def _optional_description(value):
    return 'description' not in value or isinstance(value['description'], str)


def normalize_catalog(provider, models, error_type):
    seen = set()
    result = []
    for model in models:
        if (not isinstance(model, dict) or model.get('provider') != provider
                or not _nonempty_string(model.get('id')) or not _nonempty_string(model.get('name'))
                or not _optional_description(model) or model['id'] in seen):
            raise error_type('adapter returned invalid or duplicate model metadata for provider "{}"'.format(provider), 'INVALID_CATALOG')
        seen.add(model['id'])
        item = dict(provider=model['provider'], id=model['id'], name=model['name'])
        if 'description' in model:
            item['description'] = model['description']
        if 'inputModalities' in model:
            item['inputModalities'] = list(model['inputModalities'])
        result.append(item)
    return result


def normalize_model_info(provider, identifier, model, error_type):
    route = 'for provider "{}" model "{}"'.format(provider, identifier)
    if (not isinstance(model, dict) or not isinstance(model.get('provider'), str) or model['provider'] != provider
            or not isinstance(model.get('id'), str) or model['id'] != identifier
            or not _nonempty_string(model.get('name')) or not _optional_description(model)):
        raise error_type('adapter returned invalid exact model metadata ' + route, 'INVALID_MODEL_INFO')
    if 'context' in model:
        context = model['context']
        window = context.get('contextWindow') if isinstance(context, dict) else None
        if not _integer(window) or window <= 0:
            raise error_type('adapter returned invalid context metadata ' + route, 'INVALID_MODEL_CONTEXT')
    result = dict(provider=provider, id=identifier, name=model['name'])
    if 'description' in model:
        result['description'] = model['description']
    if 'inputModalities' in model:
        result['inputModalities'] = list(model['inputModalities'])
    if 'context' in model:
        result['context'] = dict(contextWindow=model['context']['contextWindow'])
    if 'defaultMaxTokens' in model:
        maximum = model['defaultMaxTokens']
        if not _integer(maximum) or maximum <= 0 or maximum > 9007199254740991:
            raise error_type('adapter returned invalid default maxTokens ' + route, 'INVALID_MODEL_MAX_TOKENS')
        result['defaultMaxTokens'] = maximum
    if 'reasoning' not in model:
        return result
    reasoning = model['reasoning']
    efforts = reasoning.get('efforts') if isinstance(reasoning, dict) else None
    if not isinstance(efforts, list) or len(efforts) == 0:
        raise error_type('adapter returned invalid reasoning metadata ' + route, 'INVALID_MODEL_REASONING')
    seen = set()
    detached = []
    for effort in efforts:
        if (not isinstance(effort, dict) or not _nonempty_string(effort.get('id'))
                or not _nonempty_string(effort.get('name')) or not _optional_description(effort) or effort['id'] in seen):
            raise error_type('adapter returned invalid or duplicate reasoning effort metadata ' + route, 'INVALID_MODEL_REASONING')
        seen.add(effort['id'])
        item = dict(id=effort['id'], name=effort['name'])
        if 'description' in effort:
            item['description'] = effort['description']
        detached.append(item)
    if 'defaultEffort' in reasoning and reasoning['defaultEffort'] not in seen:
        raise error_type('adapter returned an unknown default reasoning effort ' + route, 'INVALID_MODEL_REASONING')
    result['reasoning'] = dict(efforts=detached)
    if 'defaultEffort' in reasoning:
        result['reasoning']['defaultEffort'] = reasoning['defaultEffort']
    return result
