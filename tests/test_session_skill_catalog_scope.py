from types import SimpleNamespace
import pytest
from dsh.api.session_catalogs import SessionSkillCatalog
from dsh.cordis.context import Context
from dsh.core.agent import Agent
from dsh.core.scope import ScopeKey, create_scope, scope_of, bind_scope_parent
from dsh.core.session import Session
from dsh.skill.registry import SkillRegistry


@pytest.mark.asyncio
@pytest.mark.parametrize('address', ['live', 'sibling', 'cold'])
async def test_remote_catalog_resolves_python_scope_identity(address):
    ctx = Context()
    await ctx.plugin(SkillRegistry)
    standing = create_scope(ctx, ScopeKey('preset'))
    first = create_scope(ctx, ScopeKey('first'))
    sibling = create_scope(ctx, ScopeKey('sibling'))
    bind_scope_parent(scope_of(first.ctx), scope_of(standing.ctx))
    bind_scope_parent(scope_of(sibling.ctx), scope_of(standing.ctx))
    first_agent = Agent(Session('live'), ctx=first.ctx)
    other_agent = Agent(Session('sibling'), ctx=sibling.ctx)
    definition = lambda name: dict(name=name, description=name, source='runtime', content=name)
    ctx.get('skills').register(definition('global'))
    standing.ctx.get('skills').register(definition('preset-skill'))
    first.ctx.get('skills').register(definition('private-skill'))
    disposed = []
    async def observe(sid):
        return SimpleNamespace(header=SimpleNamespace(cwd='C:/controlled'),
            projections=dict(values=dict(agentPreset='cordis')), dispose=lambda: disposed.append(sid))
    async def key_for(preset):
        assert preset == 'cordis'
        return scope_of(standing.ctx)
    ctx.set_service('sessionQuery', SimpleNamespace(observeSession=observe))
    ctx.set_service('agents', SimpleNamespace(get=lambda sid: {'live': first_agent, 'sibling': other_agent}.get(sid)))
    ctx.set_service('agentPresets', SimpleNamespace(serviceFor=lambda agent, name: agent.ctx.get(name), standingKeyFor=key_for))
    remote = SessionSkillCatalog(ctx)
    try:
        value = await remote.list(dict(sessionId=address), None)
        expected = ['global', 'preset-skill'] + (['private-skill'] if address == 'live' else [])
        assert sorted(row['name'] for row in value['skills']) == sorted(expected)
        assert all(row['modelInvocable'] is True for row in value['skills'])
        assert disposed == [address]
    finally:
        await ctx.fiber.dispose()
