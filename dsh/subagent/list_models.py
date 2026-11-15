"""Model-facing reads of the calling Session's authorized child routes."""
from dsh.core.session.json import UNDEFINED
from dsh.subagent.composition import parent_options
from dsh.subagent.selection import read_policy


def model_line(provider, model):
    return '%s/%s — %s%s' % (provider, model['id'], model['name'],
        ': '+model['description'] if 'description' in model else '')


async def list_subagent_models(ctx, policy_handle, request, execution):
    if execution.agent is None:
        raise RuntimeError('list_subagent_models requires a calling agent')
    routes = read_policy(policy_handle, execution.agent.session)
    selection_enabled = routes is not UNDEFINED
    if not selection_enabled:
        parent = parent_options(execution.agent)
        if parent.get('provider') is None or parent.get('model') is None:
            raise RuntimeError('cannot discover child LLM routes without a parent provider and model')
        routes = [dict(provider=parent['provider'], model=parent['model'])]
    llm = ctx.get('llm')
    if llm is None:
        raise RuntimeError('cannot discover child LLM routes because the `llm` service is unavailable')
    provider_id, model_id = request.get('provider', UNDEFINED), request.get('model', UNDEFINED)
    if model_id is not UNDEFINED and provider_id is UNDEFINED:
        raise RuntimeError('`model` requires `provider`')
    if provider_id is UNDEFINED:
        providers = [provider for provider in llm.listProviders() if any(route['provider'] == provider['id'] for route in routes)]
        return '\n'.join(provider['id']+' — '+provider['name'] for provider in providers) if providers else '(no LLM providers)'
    if not provider_id:
        raise RuntimeError('`provider` must be non-empty')
    allowed = [route for route in routes if route['provider'] == provider_id]
    if not allowed:
        raise RuntimeError('LLM provider "%s" is not allowed for this Session' % provider_id)
    providers = llm.listProviders()
    provider = next((candidate for candidate in providers if candidate['id'] == provider_id), None)
    if provider is None:
        available = ', '.join(candidate['id'] for candidate in providers if any(route['provider'] == candidate['id'] for route in routes)) or '(none)'
        raise RuntimeError('LLM provider "%s" is not registered; available providers: %s' % (provider_id, available))
    if model_id is UNDEFINED:
        models = ([model for model in await llm.listModels(provider_id) if any(route['model'] == model['id'] for route in allowed)]
            if selection_enabled else [await llm.resolveModelInfo(provider_id, allowed[0]['model'], execution.signal)])
        execution.signal.throwIfAborted()
        return '\n'.join(model_line(provider_id, model) for model in models) if models else '(no advertised models for %s)' % provider_id
    if not model_id:
        raise RuntimeError('`model` must be non-empty')
    if not any(route['model'] == model_id for route in allowed):
        raise RuntimeError('child LLM route "%s/%s" is not allowed for this Session' % (provider_id, model_id))
    model = await llm.resolveModelInfo(provider_id, model_id, execution.signal)
    reasoning = model.get('reasoning', {})
    efforts = '\n'.join('%s%s — %s%s' % (effort['id'],
        ' (default)' if reasoning.get('defaultEffort') == effort['id'] else '', effort['name'],
        ': '+effort['description'] if 'description' in effort else '') for effort in reasoning.get('efforts', []))
    return model_line(provider_id, model)+'\nReasoning efforts:\n'+(efforts or '(no advertised reasoning efforts)')


def register_list_subagent_models(ctx, policy_handle):
    async def execute(args, execution):
        return await list_subagent_models(ctx, policy_handle, args, execution)
    ctx.get('tools').register(dict(
        name='list_subagent_models',
        description='Inspect the routes available for explicit subagent model selection. No arguments: authorized providers. '
            '`provider`: that provider\'s authorized models. `provider` + `model`: that model and its reasoning efforts. '
            'Query when choosing an explicit child route or reasoning effort. '
            'Omit optional fields rather than sending empty strings.',
        parameters=dict(type='object', properties=dict(provider=dict(type='string', description='Registered LLM provider id.'),
            model=dict(type='string', description='Exact model id; requires provider.'))),
        output=dict(schema=dict(type='string'), render=lambda args, result:[dict(type='text', text=result)]),
        isConcurrencySafe=lambda *_:True, execute=execute))
