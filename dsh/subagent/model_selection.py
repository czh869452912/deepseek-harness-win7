"""Durable delegation route authority and adapter-owned preflight."""
import copy
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.cordis.schema import Schema as z
from dsh.settings.provider import install_settings_section


def validate_routes(routes):
    if not isinstance(routes, list):
        raise ValueError('subagent model selection requires an array of routes')
    seen = set()
    for route in routes:
        if not isinstance(route, dict) or any(not isinstance(route.get(key), str) or not route[key] for key in ('provider', 'model')):
            raise ValueError('subagent model selection requires non-empty provider and model ids')
        identity = (route['provider'], route['model'])
        if identity in seen:
            raise ValueError('subagent model selection repeats route {}/{}'.format(*identity))
        seen.add(identity)


def read_policy(session):
    for event in session.events:
        if event['type'] == 'subagent/model-selection-policy':
            routes = event['data']['allowedModels']
            validate_routes(routes)
            if not routes:
                raise ValueError('subagent model selection policy requires at least one route')
            return copy.deepcopy(routes)
    return None


def record_policy(session, routes):
    if read_policy(session) is None:
        session.append('subagent/model-selection-policy', {'allowedModels': copy.deepcopy(routes)})


def has_request(request):
    return any(key in request for key in ('provider', 'model', 'reasoning_effort'))


def requested_options(parent, configured, request, enabled):
    if not has_request(request):
        return copy.deepcopy(configured)
    if not enabled:
        raise ValueError('child model selection is disabled for this tool instance')
    for key in ('provider', 'model', 'reasoning_effort'):
        if key in request and (not isinstance(request[key], str) or not request[key]):
            raise ValueError('child LLM {} must be non-empty'.format(key))
    if ('provider' in request) != ('model' in request):
        raise ValueError('child LLM `provider` and `model` must be supplied together')
    result = copy.deepcopy(configured or {})
    if 'provider' in request:
        changed = any(request[key] != result.get(key, parent.get(key)) for key in ('provider', 'model'))
        if changed and 'reasoning_effort' not in request:
            result.pop('reasoningEffort', None)
        result.update({key: request[key] for key in ('provider', 'model')})
    if 'reasoning_effort' in request:
        result['reasoningEffort'] = request['reasoning_effort']
    return result


def allowed_selection(policy, parent, requested, request):
    if policy is None or not has_request(request):
        return
    route = {key: (requested or {}).get(key, parent.get(key)) for key in ('provider', 'model')}
    if any(value is None for value in route.values()):
        raise ValueError('cannot select child LLM values without an effective provider and model')
    if not any(all(item[key] == route[key] for key in route) for item in policy):
        raise ValueError('child LLM route "{provider}/{model}" is not allowed for this Session'.format(**route))


async def preflight(llm, parent, requested, signal, inherit_effort=True):
    requested = requested or {}
    route = {key: requested.get(key, parent.get(key)) for key in ('provider', 'model')}
    if any(value is None for value in route.values()):
        raise ValueError('cannot select child LLM values without an effective provider and model')
    changed = any(route[key] != parent.get(key) for key in route)
    effort = requested.get('reasoningEffort', parent.get('reasoningEffort') if inherit_effort and not changed else None)
    if effort is not None:
        route['reasoningEffort'] = effort
    await llm.resolveCallConfig(route, signal)


MODEL_SELECTION_SCHEMA = z.object({'enabled': z.boolean().default(False), 'allowedModels': z.array(z.object({
    'provider': z.string().min(1).required(), 'model': z.string().min(1).required()})).default([])})


class ModelSelectionConfig(Service):
    def __init__(self, ctx, config):
        super().__init__(ctx, 'subagentModelSelection')
        entry = dict(enabled=config.get('enabled', False), allowedModels=copy.deepcopy(config.get('allowedModels', [])))
        self.validate(entry)
        self.source = lambda: entry
        install_settings_section(ctx, 'subagent-model-selection', MODEL_SELECTION_SCHEMA, entry,
            dict(setSource=lambda source: setattr(self, 'source', source), validate=self.validate, onChange=lambda: None))

    @staticmethod
    def validate(value):
        if type(value['enabled']) is not bool:
            raise ValueError('enabled must be boolean')
        validate_routes(value['allowedModels'])
        if value['enabled'] and not value['allowedModels']:
            raise ValueError('enabled subagent model selection requires at least one allowed model')

    def current(self):
        return copy.deepcopy(self.source())


class ModelSelectionSettings(Plugin):
    id = 'subagent-model-selection-settings'

    def apply(self, ctx):
        ctx.set_service('subagentModelSelection', ModelSelectionConfig(ctx, self.config))
