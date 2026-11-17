import json

import pytest

from dsh.api.session_agents_current import CurrentSessionAgents,install_model_selection_projection
from dsh.cordis import Loader
from dsh.core.model_selection import AgentDefaultModelConfig
from dsh.presets.registry_current import CurrentAgentPresetRegistry
from dsh.typert.registry import TypertRegistry
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_current_session_activation_consumes_declarative_preset_record(tmp_path):
    fixture=await setup(tmp_path/'sessions');ctx=fixture.ctx
    try:
        await ctx.plugin(TypertRegistry)
        await ctx.plugin(AgentDefaultModelConfig,dict(provider='script',model='model'))
        install_model_selection_projection(ctx)
        await ctx.plugin(Loader)
        await ctx.plugin(CurrentAgentPresetRegistry,dict(default='minimal'))
        await ctx.agentPresets.register(dict(id='minimal',plugins=[]))
        await ctx.agentPresets.register(dict(id='other',plugins=[]))
        agents=CurrentSessionAgents(ctx);observations=[]
        for identity in [None,'other']:
            agent=await agents.ensureSession('candidate-'+str(identity),str(tmp_path/'project'),False,identity)
            observations.append(dict(requested=identity,stored=agent.session.header.agentPreset,
                projected=ctx.agentPresets.presetForSession(agent.session)))
        assert observations==[dict(requested=None,stored='minimal',projected='minimal'),dict(requested='other',stored='other',projected='other')]
        (tmp_path/'session-preset-observations.json').write_text(json.dumps(observations),encoding='utf-8')
    finally:await ctx.fiber.dispose()
