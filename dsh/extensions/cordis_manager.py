"""Native Python Host implementation of the original model-facing Cordis tools."""
from typing import Any, Dict, Optional

from dsh.cordis.plugin import Plugin
from dsh.core.session.json import UNDEFINED
from dsh.extensions.inspect_providers import host_inspect_providers
from dsh.extensions.cordis_prompt import native_contracts
from dsh.extensions.cordis_tools import execute, pre_step, present_call, render_result, run_meta


def _share_builtin_provider(registry, provider):
    """Lease one Host manifest across independently mounted Agent presets.

    Public registry.register remains strict. Queries use a live owner's Context,
    so unloading the first preset cannot strand the remaining preset's tools.
    """
    leases = getattr(registry, '_cordis_manager_leases', None)
    if leases is None:
        leases = registry._cordis_manager_leases = {}
    key = provider['manifest']['id']
    lease = leases.get(key)
    if lease is None:
        owners = []
        registration = dict(provider, query=lambda *args: owners[-1]['query'](*args))
        dispose = registry.register(registration)
        lease = leases[key] = dict(manifest=provider['manifest'], owners=owners, dispose=dispose)
    elif lease['manifest'] != provider['manifest']:
        raise ValueError('Conflicting builtin Cordis inspect manifest: ' + key)
    lease['owners'].append(provider)

    def release():
        for index, owner in enumerate(lease['owners']):
            if owner is provider:
                del lease['owners'][index]
                break
        if not lease['owners'] and leases.get(key) is lease:
            del leases[key]
            lease['dispose']()
    return release


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
            ctx.effect(lambda provider=provider: _share_builtin_provider(ctx.get('cordisInspect'), provider),
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
