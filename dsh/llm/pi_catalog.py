"""Pinned pi-ai model facts and route materialization, without a Node dependency."""
import copy
import json
from functools import lru_cache
from pathlib import Path

THINKING_LEVELS = ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
COMPLETIONS = set('supportsStore supportsDeveloperRole supportsReasoningEffort supportsUsageInStreaming supportsFinishReason maxTokensField requiresToolResultName requiresAssistantAfterToolResult requiresThinkingAsText requiresReasoningContentOnAssistantMessages thinkingFormat chatTemplateKwargs chatTemplateArgs supportsThinkingTokenBudget supportsStrictMode cacheControlFormat supportsLongCacheRetention'.split())
RESPONSES = set('supportsDeveloperRole supportsStrictMode supportsLongCacheRetention'.split())
ANTHROPIC = set('supportsEagerToolInputStreaming supportsLongCacheRetention supportsCacheControlOnTools supportsTemperature forceAdaptiveThinking allowEmptySignature supportsStrictTools'.split())
GATES = {'openai-completions': COMPLETIONS, 'openai-responses': RESPONSES,
         'azure-openai-responses': RESPONSES, 'openai-codex-responses': RESPONSES,
         'anthropic-messages': ANTHROPIC, 'bedrock-converse-stream': {'supportsStrictMode'}}
OFFERED = set().union(*GATES.values())


@lru_cache(maxsize=1)
def _catalog():
    return json.loads(Path(__file__).with_name('pi_catalog.json').read_text(encoding='utf-8'))['providers']


def catalog_provider_ids():
    return list(_catalog())


def catalog_models(provider):
    return {model['id']: copy.deepcopy(model) for model in _catalog().get(provider, {}).get('models', [])}


def _invalid(provider, message):
    raise ValueError('llm-pi-ai: provider "{}" {}'.format(provider, message))


def _compat(provider, block):
    block = {key: value for key, value in (block or {}).items() if not (isinstance(value, dict) and not value)}
    for field in block:
        if field not in OFFERED:
            _invalid(provider, 'compat field "{}" is not configurable'.format(field))
    return block


def _reasoning(provider, entry, base):
    if 'reasoningEfforts' not in entry:
        return dict(reasoning=base.get('reasoning', False))
    efforts = entry['reasoningEfforts']
    if efforts is False:
        return dict(reasoning=False)
    if not isinstance(efforts, dict) or not efforts:
        _invalid(provider, 'reasoningEfforts must declare levels or be false')
    declared = {key: value for key, value in efforts.items() if key in THINKING_LEVELS}
    for key, value in declared.items():
        if value is None and key == 'off':
            continue
        if not isinstance(value, str) or not value:
            _invalid(provider, 'reasoningEfforts.{} needs a wire value'.format(key))
    if not any(key != 'off' for key in declared):
        _invalid(provider, 'reasoningEfforts offers no level beyond off')
    mapping = {key: declared.get(key) for key in THINKING_LEVELS}
    if 'off' in declared and declared['off'] is None:
        del mapping['off']
    return dict(reasoning=True, thinkingLevelMap=mapping)


def resolve_route_models(request):
    provider = request['provider']
    defaults = catalog_models(provider)
    configured, overrides = request.get('models') or [], request.get('modelOverrides') or {}
    for identity, override in overrides.items():
        if not identity or not defaults or configured or identity not in defaults or 'id' in override:
            _invalid(provider, 'invalid modelOverrides entry "{}"'.format(identity))
    entries = configured or [dict(overrides.get(model['id'], {}), id=model['id']) for model in defaults.values()]
    if not entries:
        _invalid(provider, 'resolves no models; declare models for this route')
    apis = {model['api'] for model in defaults.values()}
    route_api = next(iter(apis)) if len(apis) == 1 else None
    route_compat = _compat(provider, request.get('compat'))
    models, caps, seen = [], {}, set()
    for entry in entries:
        identity = entry['id']
        if not identity or identity in seen:
            _invalid(provider, 'model id is empty or repeated')
        seen.add(identity)
        base = defaults.get(identity, {})
        api = request.get('api', base.get('api', route_api))
        endpoint = request.get('baseURL', base.get('baseUrl', _catalog().get(provider, {}).get('baseUrl')))
        if api is None or endpoint is None:
            _invalid(provider, 'model "{}" needs an api and baseURL'.format(identity))
        context = entry.get('contextWindow', base.get('contextWindow', request['defaultContextWindow']))
        maximum = entry.get('maxTokens', base.get('maxTokens', request['defaultMaxTokens']))
        for value in (context, maximum):
            if type(value) not in (int, float) or value <= 0 or not float(value).is_integer():
                _invalid(provider, 'model capacities must be positive integers')
        if 'maxTokens' in entry:
            caps[identity] = entry['maxTokens']
        model = dict(base, id=identity, name=entry.get('name', base.get('name', identity)), api=api,
                     provider=provider, baseUrl=endpoint,
                     input=entry.get('input') or base.get('input', request['defaultInput']),
                     cost=base.get('cost', dict(input=0, output=0, cacheRead=0, cacheWrite=0)),
                     contextWindow=context, maxTokens=maximum)
        model.update(_reasoning(provider, entry, base))
        gate = GATES.get(api, set())
        compat = {key: value for key, value in route_compat.items() if key in gate}
        for key, value in _compat(provider, entry.get('compat')).items():
            if key not in gate:
                _invalid(provider, 'model "{}" api does not take compat "{}"'.format(identity, key))
            compat[key] = value
        if compat:
            inherited = base.get('compat', {}) if base.get('api') == api else {}
            model['compat'] = dict(inherited, **compat)
        models.append(model)
    for field in route_compat:
        if not any(field in GATES.get(model['api'], set()) for model in models):
            _invalid(provider, 'no model accepts compat "{}"'.format(field))
    return copy.deepcopy(dict(models=models, configuredMaxTokens=caps))
