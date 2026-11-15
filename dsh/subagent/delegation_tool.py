"""Candidate provider-owned, immediately returning named delegation tool."""
import copy
import json
from pathlib import Path
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.utils import _UNDEFINED as SCHEMA_UNDEFINED
from dsh.core.session.json import UNDEFINED
from dsh.core.scope import scope_of
from dsh.subagent.composition import parent_options, delegation_depth
from dsh.subagent.composition_current import assert_max_depth
from dsh.subagent.selection import (POLICY, SubagentPresetSelection, read_policy,
    has_request, has_configured_selection, requested_options, preflight)
from dsh.subagent.list_models import register_list_subagent_models

METADATA=json.loads(Path(__file__).with_name('delegation_metadata.json').read_text(encoding='utf-8'))
DELEGATION_TOOLS=[]
FOLLOWUP=' Use `send_message` to steer it while running or continue its conversation after it finishes.'


class SubagentDelegationTool(Plugin):
    id='tool-subagent'
    inject=['tools','subagents','systemPrompt','sessionProjections']
    Config=Schema.object(dict(
        provider=Schema.string().required(),toolName=Schema.string().default('subagent'),
        modelSelection=Schema.boolean().default(False),modelDiscovery=Schema.boolean().default(False),
        agentOptions=Schema.object(dict(provider=Schema.string(),model=Schema.string(),reasoningEffort=Schema.string().min(1),
            maxTokens=Schema.number().step(1).min(1).max(9007199254740991))).default(SCHEMA_UNDEFINED),
        agentPreset=Schema.string().min(1),allowedAgentPresets=Schema.array(Schema.string().min(1)).min(1).default(SCHEMA_UNDEFINED),
        maxDepth=Schema.union([Schema.number().step(1).min(0).max(9007199254740991),Schema.const('provider-managed')])))

    async def apply(self,ctx):
        config=self.config
        for field in ('persona','toolFilter'):
            if field in config:
                raise RuntimeError('tool-subagent: %s is no longer supported; configure persona and tool plugins in an Agent Preset and select it with agentPreset (spawn only)' % field)
        presets=SubagentPresetSelection(config)
        if presets.configured and ctx.get('agentPresets') is None:
            raise RuntimeError('tool-subagent: agent preset selection requires the agent-presets service')
        configured_depth=config.get('maxDepth',UNDEFINED)
        if configured_depth!='provider-managed':assert_max_depth(configured_depth)
        tool_name=config.get('toolName','subagent');selection=config.get('modelSelection') is True
        projection=await ctx.get('sessionProjections').register(POLICY)
        service=ctx.get('subagents');mounted=None

        def assert_provider(provider):
            presets.assertProvider(provider)
            if service.resolveMaxDepth(configured_depth) is not UNDEFINED and not provider.capabilities.get('depthLimit'):
                raise RuntimeError('tool-subagent: provider "%s" cannot enforce maxDepth (no depthLimit capability) — set maxDepth: \'provider-managed\' to leave the recursion budget to the provider' % provider.name)
            if config.get('agentOptions',UNDEFINED) is not UNDEFINED and not provider.capabilities.get('agentOptions'):
                raise RuntimeError('tool-subagent: provider "%s" does not support child agentOptions' % provider.name)
            if selection and not provider.capabilities.get('agentOptions'):
                raise RuntimeError('tool-subagent: provider "%s" does not support child model selection' % provider.name)

        def validate(provider):
            if provider.name==config['provider']:assert_provider(provider)
        ctx.on('subagent/provider-added',validate)
        initial=service.getProvider(config['provider'])
        if initial is not None:assert_provider(initial)
        if config.get('modelDiscovery') is True:register_list_subagent_models(ctx,projection)

        def mount(provider):
            nonlocal mounted
            assert_provider(provider)
            inherited=getattr(provider,'inheritsParentContext',False)
            defaults=getattr(provider,'agentRouteDefaults',UNDEFINED)
            metadata=copy.deepcopy(METADATA['inherited' if inherited else 'fresh'])
            description=metadata['description']
            if getattr(provider,'prepareContinuable',None) is None:
                description=description[:-len(FOLLOWUP)]+' This backend does not accept follow-up messages.'
            if selection:
                description+=(' Omit `provider`, `model`, and `reasoning_effort` to use child defaults, falling back to '
                    +('this backend\'s route defaults.' if defaults is not UNDEFINED else 'compatible parent values.'))
                if inherited:description+=' Changing the route can prevent provider-side reuse of the inherited conversation prefix.'
            parameters=metadata['parameters'];properties=parameters['properties']
            if presets.choices is not UNDEFINED:
                properties['agent_preset']=dict(type='string',enum=list(presets.choices),description=presets.description)
            if selection:
                properties.update(provider=dict(type='string',description='Child LLM provider id; requires `model`.'),
                    model=dict(type='string',description='Model id within that provider; requires `provider`.'),
                    reasoning_effort=dict(type='string',description='Reasoning effort id; requires `provider` and `model`. Omit to use the selected model\'s default, even when it matches the parent or configured route.'))

            async def execute(args,execution):
                parent=execution.agent
                if parent is None:raise RuntimeError('subagent tool requires a calling agent (exec.agent was undefined)')
                routes=read_policy(projection,parent.session)
                policy=UNDEFINED if routes is UNDEFINED else dict(routes=routes)
                preset=presets.resolve(args)
                parent_route=parent_options(parent)
                needs_preflight=has_request(args) or has_configured_selection(config.get('agentOptions',UNDEFINED))
                configured=config.get('agentOptions',UNDEFINED)
                if needs_preflight and defaults is not UNDEFINED:
                    configured=dict(defaults,**({} if configured is UNDEFINED else configured))
                selected=requested_options(configured,args,selection,policy,parent_route)
                if needs_preflight:
                    llm=ctx.get('llm')
                    if llm is None:raise RuntimeError('cannot resolve the selected child LLM route because the `llm` service is unavailable')
                    await preflight(llm,parent_route,selected,execution.signal,defaults is UNDEFINED and not has_request(args))
                    if service.getProvider(config['provider']) is not provider:
                        raise RuntimeError('subagent provider "%s" changed while resolving the child LLM route; retry the delegation' % config['provider'])
                execution.signal.throwIfAborted()
                depth=service.resolveMaxDepth(configured_depth)
                request=dict(provider=config['provider'],label=args['description'],prompt=[dict(type='text',text=args['prompt'])],
                    parent=parent,signal=execution.signal,delivery='parent')
                for key,value in [('cwd',args.get('cwd',UNDEFINED)),('name',args.get('name',UNDEFINED)),
                    ('agentPreset',preset),('agentOptions',selected),('maxDepth',depth)]:
                    if value is not UNDEFINED:request[key]=value
                started=await service.startActivation(request)
                return dict(kind='activation',name=started['name'])

            definition=dict(name=tool_name,description=description,parameters=parameters,execute=execute,isConcurrencySafe=lambda *_:True,
                output=dict(schema=metadata['outputSchema'],render=lambda args,value:[dict(type='text',text='started subagent '+value['name'])],
                    presentationMeta=lambda args,value:dict(kind=value['kind'],name=value['name'])))
            canonical=None
            def setup():
                nonlocal canonical
                unregister=ctx.get('tools').register(definition)
                canonical=ctx.get('tools').get_tool(tool_name,scope_of(ctx))
                DELEGATION_TOOLS.append(canonical)
                def dispose():
                    DELEGATION_TOOLS[:]=[tool for tool in DELEGATION_TOOLS if tool is not canonical]
                    unregister()
                return dispose
            dispose=ctx.effect(setup)
            mounted=dict(provider=provider,definition=canonical,dispose=dispose)

        def added(provider):
            if provider.name==config['provider'] and mounted is None:mount(provider)
        def removed(name):
            nonlocal mounted
            if name!=config['provider'] or mounted is None:return
            mounted['dispose']();mounted=None
        ctx.on('subagent/provider-added',added)
        ctx.on('subagent/provider-removed',removed)
        present=service.getProvider(config['provider'])
        if present is not None:mount(present)
        else:ctx.logger.info('subagent provider "%s" not registered yet; the "%s" tool will register when it appears' % (config['provider'],tool_name))

        def guidance(context):
            if mounted is None:return ''
            visible=sorted(tool.name for tool in DELEGATION_TOOLS if ctx.get('tools').get_tool(tool.name,context.get('scope')) is tool)
            if not visible or visible[0]!=tool_name:return ''
            return METADATA['fresh']['guidance'].replace('`subagent`',' or '.join('`'+name+'`' for name in visible),1)
        def depth_context(context):
            agent=context.get('agent')
            if agent is None or mounted is None or ctx.get('tools').get_tool(tool_name,context.get('scope')) is not mounted['definition']:return ''
            maximum=service.resolveMaxDepth(configured_depth)
            if maximum is UNDEFINED:return ''
            depth=delegation_depth(agent)
            if depth<maximum:return ''
            return ('Delegation depth for `%s`: current %s, maximum %s, remaining levels 0. Do not call `%s` at this depth; carry out the work directly.'
                % (tool_name,depth,maximum,tool_name))
        prompt=ctx.get('systemPrompt')
        prompt.section(dict(name='tool:'+tool_name,order=prompt.getSectionOrder('TOOL_SUBAGENT'),text=guidance))
        prompt.context(dict(name='tool:'+tool_name+':depth',order=prompt.getContextOrder('SUBAGENT_DELEGATION'),text=depth_context))
