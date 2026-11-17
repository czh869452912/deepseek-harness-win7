"""Native Creative seven-tool composition beside current read-only inspection.

This is the project's explicit Python development extension. Current upstream
tool-cordis remains the two read-only tools; its four shared Host providers are
owned by their process plugin, never leased or shadowed by Agent presets.
"""
from dsh.extensions.cordis_manager import CordisManagerPlugin, _share_builtin_provider
from dsh.extensions.cordis_prompt import native_contracts
from dsh.extensions.cordis_tools import execute, pre_step, present_call, render_result, run_meta
from dsh.extensions.inspect_providers import host_inspect_providers
from dsh.extensions.inspect_tools_current import CurrentCordisInspectTools


class CurrentNativeCordisManager(CordisManagerPlugin):
    id = 'cordis-manager'
    name = '@deepseek-ai/dsh-cordis-manager'

    async def apply(self, ctx):
        self.runner = ctx.get('dynamicCordisRunner')
        contracts = native_contracts()
        ctx.get('systemPrompt').section(dict(name='tool:cordis-native', order=contracts['order'], text=contracts['prompt']))
        # Only the Python evaluator's additional Builtin directory is leased.
        # Service/Event/Config/Tool belong to CurrentCordisInspectProviders.
        builtin = next(provider for provider in host_inspect_providers(ctx) if provider['manifest']['id'] == 'Builtin')
        ctx.effect(lambda: _share_builtin_provider(ctx.get('cordisInspect'), builtin), 'cordis-manager: Python Builtin')
        await ctx.plugin(CurrentCordisInspectTools)
        for contract in contracts['definitions']:
            operation = contract['name'][len('cordis_'):]
            if operation in ('inspect_list', 'inspect_query'):
                continue
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
