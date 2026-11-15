"""Local v4 backends contribute creation inputs; the manager owns execution."""
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.subagent.descriptor import completed_turn_prefix


class SpawnInProcessProvider:
    capabilities = dict(agentOptions=True,agentPreset=True,outputSchema=True,depthLimit=True)
    inheritsParentContext = False

    def __init__(self, name='spawn'):
        self.name = name

    async def prepareContinuable(self, request):
        return {}


class ForkInProcessProvider(SpawnInProcessProvider):
    capabilities = dict(agentOptions=True,agentPreset=False,outputSchema=True,depthLimit=True)
    inheritsParentContext = True

    def __init__(self, name='fork'):
        super().__init__(name)

    async def prepareContinuable(self, request):
        seed = completed_turn_prefix(request['parent'])
        return dict(seed=seed) if seed else {}


class SpawnInProcessPlugin(Plugin):
    id = 'subagent-spawn-in-process'
    inject = ['subagents']
    Config = Schema.object(dict(providerName=Schema.string().default('spawn')))
    def apply(self, ctx):
        ctx.get('subagents').registerProvider(SpawnInProcessProvider(self.config.get('providerName','spawn')))


class ForkInProcessPlugin(SpawnInProcessPlugin):
    id = 'subagent-fork-in-process'
    Config = Schema.object(dict(providerName=Schema.string().default('fork')))
    def apply(self, ctx):
        ctx.get('subagents').registerProvider(ForkInProcessProvider(self.config.get('providerName','fork')))
