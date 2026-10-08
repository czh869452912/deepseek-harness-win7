"""Model-facing delegation through published providers and owned Agent runs."""
import asyncio
import weakref

from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.core.scope import scope_of, scope_chain_of
from dsh.session.preparations import throw_aborted
from dsh.subagent.composition import parent_options, valid_depth
from dsh.subagent.model_selection import read_policy, record_policy, requested_options, allowed_selection, preflight, has_request
from dsh.subagent.runtime import settle_run


def text(value):
    return [{'type': 'text', 'text': value}]


def object_schema(fields, required=None):
    return dict(type='object', additionalProperties=False, properties=fields, required=list(fields) if required is None else required)


def register(ctx, name, description, fields, execute, output_schema, render, required=None):
    parameters = object_schema(fields, required)
    parameters.pop('additionalProperties')
    if not parameters['required']:
        parameters.pop('required')
    return ctx.get('tools').register(dict(name=name, description=description,
        parameters=parameters, execute=execute, isConcurrencySafe=lambda *_: True,
        output=dict(schema=output_schema, render=render)))


def agent_of(execution):
    agent = getattr(execution, 'agent', None)
    if agent is None:
        raise ValueError('subagent tool requires a calling agent')
    return agent


async def foreground(run):
    failure, value = None, None
    try:
        result = await run.result
        if result['stopReason'] != 'completed':
            message = {'aborted': 'subagent run was cancelled', 'error': 'subagent run failed',
                'max-tokens': 'subagent run hit its token limit before finishing',
                'refusal': 'subagent declined the task'}.get(result['stopReason'],
                    'subagent run ended abnormally ({})'.format(result['stopReason']))
            if 'diagnostic' in result:
                message += '\nDiagnostic: ' + result['diagnostic']
            partial = ''.join(block['text'] for block in result['output'] if block['type'] == 'text')
            if partial:
                message += '\nPartial output before the run ended:\n' + partial
            raise RuntimeError(message)
        value = dict(kind='foreground', runId=run.id, output=result['output'])
    except BaseException as error:
        failure = error
    try:
        await run.dispose()
    except BaseException as error:
        if failure is not None:
            raise RuntimeError('subagent run failed: {}; dispose failed: {}'.format(failure, error)) from failure
        raise
    if failure is not None:
        raise failure
    return value


def register_models(ctx, routes):
    async def execute(args, execution):
        llm = ctx.get('llm')
        if llm is None:
            raise ValueError('cannot discover child LLM routes because the `llm` service is unavailable')
        provider, model = args.get('provider'), args.get('model')
        if model is not None and provider is None:
            raise ValueError('`model` requires `provider`')
        providers = [item for item in llm.listProviders() if any(route['provider'] == item['id'] for route in routes)]
        if provider is None:
            return '\n'.join('{} — {}'.format(item['id'], item['name']) for item in providers) or '(no LLM providers)'
        if not provider:
            raise ValueError('`provider` must be non-empty')
        allowed = [route for route in routes if route['provider'] == provider]
        if not allowed:
            raise ValueError('LLM provider "{}" is not allowed for this Session'.format(provider))
        if not any(item['id'] == provider for item in providers):
            raise ValueError('LLM provider "{}" is not registered; available providers: {}'.format(provider, ', '.join(item['id'] for item in providers) or '(none)'))
        def line(item):
            return '{}/{} — {}{}'.format(provider, item['id'], item['name'], ': ' + item['description'] if 'description' in item else '')
        if model is None:
            models = [item for item in await llm.list_models(provider) if any(route['model'] == item['id'] for route in allowed)]
            return '\n'.join(line(item) for item in models) or '(no advertised models for {})'.format(provider)
        if not model:
            raise ValueError('`model` must be non-empty')
        if not any(route['model'] == model for route in allowed):
            raise ValueError('child LLM route "{}/{}" is not allowed for this Session'.format(provider, model))
        info = await llm.resolve_model_info(provider, model, execution.signal)
        reasoning = info.get('reasoning', {})
        efforts = []
        for effort in reasoning.get('efforts', []):
            if isinstance(effort, str):
                effort = dict(id=effort, name=effort)
            efforts.append('{}{} — {}{}'.format(effort['id'], ' (default)' if effort['id'] == reasoning.get('defaultEffort') else '',
                                                effort['name'], ': ' + effort['description'] if 'description' in effort else ''))
        return line(info) + '\nReasoning efforts:\n' + ('\n'.join(efforts) or '(no advertised reasoning efforts)')
    register(ctx, 'list_subagent_models', "Discover LLM routes for subagents without changing the current Agent. Call with no arguments to list registered providers, with `provider` to list its advertised models, or with `provider` and `model` to inspect that exact model and its reasoning efforts. Catalog membership is advisory: an adapter may accept an unlisted model id. Use the returned ids with a delegation tool's `provider`, `model`, and `reasoning_effort` fields.",
             {'provider': {'type': 'string', 'description': 'Registered LLM provider id. Omit to list providers.'},
              'model': {'type': 'string', 'description': "Exact model id to inspect. Requires provider; omit to list that provider's advertised models."}}, execute, {'type': 'string'}, lambda _, value: text(value), [])


class CanonicalToolSubagent(Plugin):
    id = 'tool-subagent'
    inject = ['tools', 'subagents', 'systemPrompt']

    def apply(self, ctx):
        config = dict(self.config)
        provider_name = config.get('provider')
        if not isinstance(provider_name, str) or not provider_name:
            raise ValueError('tool-subagent requires a provider')
        maximum = config.get('maxDepth', 3)
        if maximum != 'provider-managed':
            valid_depth(maximum)
        if 'toolFilter' in config:
            restriction = config['toolFilter']
            if not isinstance(restriction, dict) or not set(restriction) & {'allow', 'deny'}:
                raise ValueError('toolFilter must declare allow or deny')
            for items in restriction.values():
                if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                    raise ValueError('toolFilter values must be tool name arrays')
                if any(ctx.get('tools').get(item, scope_of(ctx)) is None for item in items):
                    raise ValueError('toolFilter names an unknown tool')
        background = config.get('enableRunInBackground', True)
        mode = config.get('backgroundMode', 'one-shot')
        if mode not in ('one-shot', 'continuable'):
            raise ValueError('invalid backgroundMode')
        continuable = mode == 'continuable'
        name = config.get('toolName', 'subagent')
        selection = config.get('modelSelectionSettings', False)

        def validate(provider):
            needs = [(maximum != 'provider-managed', 'depthLimit'), ('agentOptions' in config or selection, 'agentOptions'),
                     ('persona' in config, 'persona'), ('toolFilter' in config, 'toolFilter')]
            if any(needed and not provider.capabilities.get(capability) for needed, capability in needs):
                raise ValueError('subagent provider cannot enforce configured capabilities')
            if continuable and not callable(getattr(provider, 'prepareContinuable', None)):
                raise ValueError('subagent provider does not support continuable children')
        ctx.on('subagent/provider-added', lambda provider: validate(provider) if provider.name == provider_name else None)
        present = ctx.get('subagents').getProvider(provider_name)
        if present is not None:
            validate(present)

        def install(runtime_ctx, policy):
            if policy is not None:
                register_models(runtime_ctx, policy)
            mounted = [None]
            def mount(provider):
                if provider.name != provider_name or mounted[0] is not None:
                    return
                validate(provider)
                fields = dict(description={'type': 'string', 'description': 'A short (3-5 word) description of the delegated task, for display.'},
                    prompt={'type': 'string', 'description': "The task for the subagent. It already sees this conversation's completed turns, so build on them freely and state only what is new."
                        if provider.inheritsParentContext else "The complete, self-contained task for the subagent. It does not share this conversation's context, so include everything it needs."})
                if background:
                    fields['run_in_background'] = {'type': 'boolean', 'description': 'Whether to run as a background job and return its id. Defaults to false; collect with job_output or stop with job_kill.'
                        if not continuable else 'Whether to run in the background and return a durable subagent id immediately. Defaults to true. Set false to wait for the result when your next action depends on it.'}
                if policy is not None:
                    route_defaults = getattr(provider, 'agentRouteDefaults', None) is not None
                    fields.update(provider={'type': 'string', 'description': "LLM provider route for the child. Supply together with model; omit both to use configured child defaults or this provider's route defaults." if route_defaults else 'LLM provider route for the child. Supply together with model; omit both to use configured child defaults or inherit the parent route.'},
                        model={'type': 'string', 'description': "Model id interpreted by provider. Supply together with provider; omit both to use configured child defaults or this provider's route defaults." if route_defaults else 'Model id interpreted by provider. Supply together with provider; omit both to use configured child defaults or inherit the parent route.'},
                        reasoning_effort={'type': 'string', 'description': "Adapter-owned reasoning effort for the effective child route. Omit to use a compatible configured effort or the selected model's default." if route_defaults else "Adapter-owned reasoning effort for the effective child route. Omit to inherit a compatible configured/parent effort or use a newly selected model's default."})
                async def execute(args, execution):
                    parent = agent_of(execution)
                    inherited = parent_options(parent)
                    configured = config.get('agentOptions')
                    route_check = has_request(args) or any(key in (configured or {}) for key in ('provider', 'model', 'reasoningEffort'))
                    defaults = getattr(provider, 'agentRouteDefaults', None)
                    if route_check and defaults is not None:
                        configured = dict(defaults, **(configured or {}))
                    requested = requested_options(inherited, configured, args, policy is not None)
                    allowed_selection(policy, inherited, requested, args)
                    if route_check:
                        llm = runtime_ctx.get('llm')
                        if llm is None:
                            raise ValueError('selected child LLM route requires llm service')
                        await preflight(llm, inherited, requested, execution.signal, defaults is None)
                        if runtime_ctx.get('subagents').getProvider(provider_name) is not provider:
                            raise ValueError('subagent provider changed while resolving child LLM route; retry delegation')
                    throw_aborted(execution.signal)
                    request = dict(label=args['description'], prompt=text(args['prompt']), parent=parent)
                    if requested is not None:
                        request['agentOptions'] = requested
                    for key in ('persona', 'toolFilter'):
                        if key in config:
                            request[key] = config[key]
                    if maximum != 'provider-managed':
                        request['maxDepth'] = maximum
                    if not background and args.get('run_in_background') is True:
                        raise ValueError('run_in_background is disabled for this tool instance')
                    run_background = background and args.get('run_in_background', continuable)
                    service = runtime_ctx.get('subagents')
                    if run_background and continuable:
                        started = await service.startContinuable(dict(provider=provider_name, label=args['description'], request=request, signal=execution.signal))
                        return dict(kind='continuable', subagentId=started['childId'])
                    if run_background:
                        jobs = runtime_ctx.get('jobs')
                        if jobs is None:
                            raise ValueError('background jobs unavailable')
                        def run():
                            controller = AbortController()
                            async def finish():
                                try:
                                    return await settle_run(await service.start(provider_name, dict(request, signal=controller.signal)))
                                except Exception as error:
                                    return dict(status='failed', detail=str(error))
                            return dict(cancel=lambda reason=None: controller.abort(reason or 'background subagent task killed'), done=asyncio.create_task(finish()))
                        identity = jobs.start(dict(kind='subagent', label=args['description'], owner=parent, run=run))
                        return dict(kind='background', jobId=identity)
                    return await foreground(await service.start(provider_name, dict(request, signal=execution.signal)))
                output = {'oneOf': [object_schema(dict(kind={'type': 'string', 'const': 'background'}, jobId={'type': 'string'})),
                    object_schema(dict(kind={'type': 'string', 'const': 'continuable'}, subagentId={'type': 'string'})),
                    object_schema(dict(kind={'type': 'string', 'const': 'foreground'}, runId={'type': 'string'}, output={'type': 'array', 'items': {}}))]}
                def render(_, value):
                    if value['kind'] == 'foreground':
                        return text(''.join(item['text'] for item in value['output'] if isinstance(item, dict) and item.get('type') == 'text'))
                    return text('started subagent ' + value['subagentId'] if value['kind'] == 'continuable' else 'started background subagent job ' + value['jobId'])
                description = ("Delegate a task to a subagent that inherits this conversation: a child agent seeded with all completed turns so far (it does not see the current in-flight turn). Use this when the subtask builds on this conversation's context — a follow-up analysis, a review, a continuation — without consuming this conversation's context for the work itself. You receive its result, not its intermediate steps." if provider.inheritsParentContext else
                               "Delegate a self-contained task to a subagent (a separate agent that works in its own context) to offload focused, independent work — research, a scoped implementation, an analysis — so it does not consume this conversation's context. The subagent returns its result, not its intermediate steps. Give it a complete, standalone prompt: it does not see this conversation.")
                description += (' This tool runs in the background by default, immediately returns a durable subagent id, and keeps the child conversation available for later turns. When that run settles, the runtime sends the parent a notice containing its outcome and any final assistant message; `send_message` starts a later turn in the same child conversation. Set `run_in_background: false` only when your next action depends on receiving the result.'
                                if background and continuable else ' This call waits for the result by default. Set `run_in_background: true` to return a job id; collect with `job_output` and stop with `job_kill`.' if background else ' This call waits for the subagent and returns its result.')
                if policy is not None:
                    description += (" Child LLM selection is optional. Omit `provider`, `model`, and `reasoning_effort` to use configured child defaults and this provider's route defaults. Supply `provider` and `model` together after using `list_subagent_models` to inspect advertised routes and efforts. Changing the effective route without naming an effort uses the selected model's default effort." if route_defaults else " Child LLM selection is optional. Omit `provider`, `model`, and `reasoning_effort` to use configured child defaults and inherit compatible missing values from the parent Agent. Supply `provider` and `model` together after using `list_subagent_models` to inspect advertised routes and efforts. Changing the effective route without naming an effort uses the selected model's default effort.")
                    if provider.inheritsParentContext:
                        description += ' Changing the route can prevent provider-side reuse of the inherited conversation prefix.'
                mounted[0] = register(runtime_ctx, name, description, fields, execute, output, render, ['description', 'prompt'])
            def removed(removed_name):
                if removed_name == provider_name and mounted[0] is not None:
                    dispose, mounted[0] = mounted[0], None
                    dispose()
            runtime_ctx.on('subagent/provider-added', mount)
            runtime_ctx.on('subagent/provider-removed', removed)
            provider = runtime_ctx.get('subagents').getProvider(provider_name)
            if provider is not None:
                mount(provider)
            if background and continuable:
                runtime_ctx.get('systemPrompt').section(dict(name='tool:' + name, order=2800,
                    text=lambda context: '' if mounted[0] is None or runtime_ctx.get('tools').get(name, context.get('scope')) is None else
                    "Use {} in the background by default. Start independent delegations together in one assistant message and continue useful work while they run. Set `run_in_background: false` only when your next action depends on that subagent's result. When a background run settles, the runtime sends you a notice containing its outcome and any final assistant message.".format(name)))

        if not selection:
            install(ctx, None)
            return
        settings = ctx.get('subagentModelSelection')
        composition_scope = scope_of(ctx)
        if settings is None or composition_scope is None:
            raise ValueError('modelSelectionSettings requires host settings and an Agent or preset scope')
        def select(agent):
            routes = read_policy(agent.session)
            if routes is None:
                parent_id = agent.session.header.parentSession if agent.session.header.origin == 'subagent' else None
                if parent_id is not None:
                    parent = ctx.get('agents').get(parent_id)
                    routes = read_policy(parent.session) if parent is not None else None
                elif agent.session.firstLiveSeq == 0:
                    current = settings.current()
                    routes = current['allowedModels'] if current['enabled'] else None
            if routes is not None:
                record_policy(agent.session, routes)
            return routes
        current_agent, association = None, ctx
        while association is not None:
            if 'agent' in association.__dict__:
                current_agent = association.__dict__['agent']
                break
            association = association.__dict__.get('_parent')
        if current_agent is not None:
            install(ctx, select(current_agent))
            return
        installed, installing = weakref.WeakKeyDictionary(), weakref.WeakSet()
        def admit(agent):
            if agent in installed or agent in installing:
                return
            installing.add(agent)
            try:
                policy = select(agent)
                installed[agent] = agent.ctx.inject(['tools', 'subagents', 'systemPrompt'], lambda runtime_ctx: install(runtime_ctx, policy))
            finally:
                installing.discard(agent)
        def remove(agent):
            fiber = installed.pop(agent, None)
            if fiber is not None:
                job = asyncio.create_task(fiber.dispose())
                job.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        def reconcile(*_):
            for agent in ctx.get('agents').list():
                if composition_scope in scope_chain_of(scope_of(agent.ctx)):
                    admit(agent)
                else:
                    remove(agent)
        ctx.on('agent/created', lambda payload: admit(payload['agent']))
        ctx.on('agent/disposed', lambda payload: remove(payload['agent']))
        ctx.on('tools/change', reconcile)
        async def cleanup():
            fibers = list(installed.values())
            installed.clear()
            await asyncio.gather(*(fiber.dispose() for fiber in fibers))
        ctx.effect(lambda: cleanup, 'subagent model selection scopes')
