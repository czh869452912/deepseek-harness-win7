import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session
from dsh.core.abort import AbortController
from dsh.llm.llm_service import LlmRuntime
from dsh.llm.llm_deepseek import LLMDeepSeekPlugin
from dsh.subagent.model_selection import (requested_options, allowed_selection, preflight, read_policy,
                                         record_policy, ModelSelectionSettings)
from test_deepseek_config_snapshot import MemorySettings


def test_route_changes_clear_effort_and_durable_authority_is_detached():
    parent = dict(provider='a', model='one', reasoningEffort='high')
    request = dict(provider='b', model='two')
    resolved = requested_options(parent, dict(reasoningEffort='max'), request, True)
    assert resolved == request
    with pytest.raises(ValueError, match='disabled'):
        requested_options(parent, None, request, False)
    with pytest.raises(ValueError, match='together'):
        requested_options(parent, None, {'model': 'two'}, True)
    routes = [dict(provider='b', model='two')]
    allowed_selection(routes, parent, resolved, request)
    with pytest.raises(ValueError, match='not allowed'):
        allowed_selection(routes, parent, None, {'reasoning_effort': 'high'})
    session = Session.create('policy')
    record_policy(session, routes)
    routes[0]['model'] = 'changed'
    assert read_policy(session)[0]['model'] == 'two'
    record_policy(session, routes)
    assert len(session.events) == 1


@pytest.mark.asyncio
async def test_settings_validate_updates_and_keep_last_good():
    ctx = Context()
    await ctx.plugin(MemorySettings)
    await ctx.plugin(ModelSelectionSettings)
    try:
        settings, config = ctx.get('settings'), ctx.get('subagentModelSelection')
        assert config.current() == dict(enabled=False, allowedModels=[])
        valid = dict(enabled=True, allowedModels=[dict(provider='deepseek-official', model='deepseek-v4-flash')])
        await settings.replace('subagent-model-selection', valid)
        assert config.current() == valid
        with pytest.raises(Exception):
            await settings.replace('subagent-model-selection', dict(enabled=True, allowedModels=[]))
        assert config.current() == valid
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_native_adapter_preflight_returns_official_effort_metadata_and_rejects_unregistered_route():
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    await ctx.plugin(LLMDeepSeekPlugin)
    try:
        llm = ctx.get('llm')
        info = await llm.resolve_model_info('deepseek-official', 'deepseek-v4-flash')
        assert [effort['id'] for effort in info['reasoning']['efforts']] == ['off', 'low', 'high', 'max']
        assert all(effort['name'] and effort['description'] for effort in info['reasoning']['efforts'])
        parent = dict(provider='deepseek-official', model='deepseek-v4-flash', reasoningEffort='high')
        await preflight(llm, parent, {'reasoningEffort': 'max'}, AbortController().signal)
        with pytest.raises(Exception, match='does not support'):
            await preflight(llm, parent, {'reasoningEffort': 'unknown'}, AbortController().signal)
        with pytest.raises(Exception, match='not registered'):
            await preflight(llm, parent, dict(provider='missing', model='model'), AbortController().signal)
    finally:
        await ctx.fiber.dispose()
