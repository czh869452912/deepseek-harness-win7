"""Version-gated listed model knowledge, deployment overrides and refusal facts."""
import copy

from dsh import __version__
from dsh.boot.semver import parse
from dsh.llm.deepseek_config_current import resolveAdapterOptions
from dsh.llm.llm_service import LlmError


def _layered(model, layer):
    merged = dict(model, **copy.deepcopy(layer))
    if 'image' not in (merged.get('inputModalities') or []):
        for key in ('imagePixelBudget','imageMaxBytes'):
            if key not in layer: merged.pop(key,None)
    return merged


def _listed(base, entry, facts, route_max_tokens):
    inherited = copy.deepcopy(base)
    for key in ('systemPromptUpdate','toolUpdate'):
        if facts.get(key) == 'leading-only': inherited.pop(key,None)
    layer = dict(inputModalities=list(facts['inputModalities']))
    if 'name' in entry: layer['name'] = entry['name']
    if 'contextWindow' in facts: layer['contextWindow'] = facts['contextWindow']
    if 'maxOutputTokens' in facts: layer['maxTokens'] = min(route_max_tokens,facts['maxOutputTokens'])
    if facts.get('systemPromptUpdate') == 'in-history': layer['systemPromptUpdate'] = 'in-history'
    if facts.get('toolUpdate') not in (None,'leading-only'): layer['toolUpdate'] = facts['toolUpdate']
    return _layered(inherited,layer)


def _gate(entry, known, version, problems):
    requirement = entry['requirement']
    kind = requirement['kind']
    if kind == 'none': return None if known else dict(kind='unsupported')
    if kind == 'min-version':
        try: required = parse(requirement['version'])
        except ValueError: pass
        else:
            return None if parse(version) >= required else dict(kind='upgrade-required',requiredVersion=requirement['version'])
    elif kind != 'invalid': raise AssertionError('model listing client requirement')
    problems.append('model "'+entry['id']+'" declares an unreadable client requirement')
    return dict(kind='unsupported')


def resolveListedCatalog(input):
    supported = {model['id']:model for model in input['supported']}
    problems, errors = [], []
    overrides = input['overrides']
    def with_override(model):
        if model['id'] not in overrides: return model
        candidate = _layered(model,overrides[model['id']])
        try: resolveAdapterOptions(dict(models=[candidate]))
        except Exception as error:
            name = getattr(error,'name','TypeError' if isinstance(error,TypeError) else 'Error')
            errors.append('modelOverrides.'+model['id']+' does not apply ('+name+': '+str(error)+')')
            return model
        return candidate
    listing = input.get('listing')
    refusals, badges = {}, {}
    if listing is None:
        resolution = resolveAdapterOptions(dict(models=[with_override(model) for model in input['supported']]))['models']
        return dict(offered=resolution,resolution=resolution,refusals=refusals,badges=badges,problems=problems,overrideErrors=errors)
    offered = []
    for entry in listing:
        model_id = entry['id']
        refusal = _gate(entry,model_id in supported,input['clientVersion'],problems)
        if refusal is not None:
            refusals[model_id] = refusal
            continue
        capabilities = entry['capabilities']
        if not capabilities['usable']:
            problems.append('model "'+model_id+'" '+capabilities['reason'])
            refusals[model_id] = dict(kind='unsupported')
            continue
        offered.append(with_override(_listed(supported.get(model_id,dict(id=model_id)),entry,capabilities['facts'],input['routeMaxTokens'])))
        badge = entry.get('badge')
        if badge is not None:
            if badge['kind'] == 'badge': badges[model_id] = copy.deepcopy(badge['badge'])
            elif badge['kind'] == 'invalid': problems.append('model "'+model_id+'" shows no badge: '+badge['reason'])
            else: raise AssertionError('listed badge')
    offered_ids, listed_ids = {model['id'] for model in offered}, {entry['id'] for entry in listing}
    for model_id in overrides:
        if model_id not in listed_ids and model_id not in supported:
            errors.append('modelOverrides names "'+model_id+'", which neither the model listing nor the built-in catalog describes')
    resolution = resolveAdapterOptions(dict(models=offered+[with_override(model) for model in input['supported'] if model['id'] not in offered_ids]))['models']
    return dict(offered=resolution[:len(offered)],resolution=resolution,refusals=refusals,badges=badges,problems=problems,overrideErrors=errors)


def refuseListedModel(model, refusal):
    if refusal is None: return
    if refusal['kind'] == 'upgrade-required':
        raise LlmError('DeepSeek model "'+model+'" requires DeepSeek Harness '+refusal['requiredVersion']+' or later; current version is '+__version__, 'CLIENT_UPGRADE_REQUIRED')
    if refusal['kind'] == 'unsupported':
        raise LlmError('DeepSeek model "'+model+'" is not supported by DeepSeek Harness; current version is '+__version__, 'MODEL_UNSUPPORTED')
    raise AssertionError('listed catalog refusal')
