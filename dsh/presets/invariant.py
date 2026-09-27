"""Package-owned agent preset invariant companion from the pinned upstream."""
from dsh.cordis.plugin import Plugin
from dsh.diagnostics.invariants import registration_result
from dsh.presets.mount import leaked_services, live_preset_mounts

PACKAGE_NAME = '@deepseek-ai/dsh-agent-presets'

def install(ctx, fail):
    def on_service(name, *args):
        for mount in live_preset_mounts():
            leaked = leaked_services(ctx, mount.fiber)
            if leaked:
                fail('preset "%s" published process-global service(s) [%s] after its mount was audited '
                     '(observed while notifying "%s") — a preset service must sit behind an `isolate` realm '
                     'or move to the host composition' % (mount.preset_id, ', '.join(leaked), name))
    ctx.on('internal/service', on_service, global_listener=True)
    def on_assemble(assembly, context, next_fn):
        presets = ctx.get('agentPresets', None)
        agent = context.get('agent') if isinstance(context, dict) else getattr(context, 'agent', None)
        if presets is not None and presets.roots and agent is not None and presets.composed_preset(agent.ctx) is None:
            fail('agent "%s" addressed a model without joining any agent preset while a roster is composed; '
                 'its tools, prompt sections, and skill catalog resolve against the empty global layer' % agent.id)
        return next_fn()
    ctx.on('system-prompt/assemble', on_assemble)

class AgentPresetsInvariantPlugin(Plugin):
    name = 'agent-presets-invariant'
    inject = ['invariants']
    def apply(self, ctx):
        return registration_result(ctx.get('invariants').register(PACKAGE_NAME, install))

name = AgentPresetsInvariantPlugin.name
inject = AgentPresetsInvariantPlugin.inject
def apply(ctx):
    return AgentPresetsInvariantPlugin().apply(ctx)
