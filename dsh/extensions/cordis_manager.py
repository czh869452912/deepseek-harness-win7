"""Native Python Host implementation of the original model-facing Cordis tools."""
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_providers import host_inspect_providers
from dsh.extensions.cordis_prompt import native_contracts
from dsh.extensions.cordis_tools import execute, pre_step, present_call, render_result, run_meta
from dsh.extensions.cordis_export import register_export_tool


class CordisManagerPlugin(Plugin):
    id = "tool-cordis"
    name = "@deepseek-ai/dsh-tool-cordis"
    inject = ["tools", "systemPrompt", "dynamicCordisRunner", "cordisInspect"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.runner = None

    def apply(self, ctx):
        self.runner = ctx.get('dynamicCordisRunner')
        contracts = native_contracts()
        ctx.get('systemPrompt').section(dict(name='tool:cordis', order=contracts['order'], text=contracts['prompt']))
        for provider in host_inspect_providers(ctx):
            ctx.effect(lambda provider=provider: ctx.get('cordisInspect').register(provider),
                       'tool-cordis: inspect ' + provider['manifest']['id'])
        for contract in contracts['definitions']:
            operation = contract['name'][len('cordis_'):]
            output = dict(schema=contract['outputSchema'],
                          render=lambda args, value, operation=operation: render_result(operation, args, value))
            if operation == 'define':
                output['presentationMeta'] = lambda _args, value: {key: value[key] for key in ('pluginId', 'packageId')}
            elif operation == 'run':
                output['presentationMeta'] = run_meta
            ctx.get('tools').register(dict(name=contract['name'], description=contract['description'],
                parameters=contract['parameters'], output=output,
                execute=lambda args, execution, operation=operation: execute(ctx, operation, args, execution),
                presentCall=lambda args, operation=operation: present_call(operation, args)))
        register_export_tool(ctx)
        ctx.on('agent/pre-step', lambda payload, next_fn: pre_step(ctx, payload, next_fn))

    def on_prompt_assemble(self, prompt):
        return prompt + '\n\n' + native_contracts()['prompt']

    async def handle_inspect_list(self):
        return dict(providers=self.ctx.get('cordisInspect').list())

    async def handle_inspect_query(self, platform, provider, method, input=UNDEFINED, agent=None, signal=None):
        if agent is None:
            raise ValueError('Cordis dynamic tools require an Agent-backed session')
        data = await self.ctx.get('cordisInspect').query(platform, provider, method, input, agent, signal)
        return dict(platform=platform, provider=provider, method=method, data=data)
