"""Regressions discovered through the actual canonical browser RPC composition."""
import copy
import json
from types import SimpleNamespace

import pytest

from dsh.boot.plugin_registry import resolve_harness_plugin
from dsh.cordis.context import Context
from dsh.core.agent import Agent
from dsh.core.session import SessionStore
from dsh.api.session import SessionController
from dsh.llm.llm_service import LlmError
from dsh.settings.provider import SettingsProvider
from dsh.typert.registry import TypertRegistry
from dsh.typert.dispatch import RemoteDispatcher, assert_json
from dsh.typert.protocol import TypertLookupProvider
from dsh.typert.artifact import UNDEFINED
from dsh.typert.artifact import read_generated_artifact
from dsh.host.connection.rpc_host import rpc_fetch


class MemorySettings(SettingsProvider):
    def _load_document(self):
        return copy.deepcopy(self._document)

    def _persist_section(self, ns, section):
        self._document = dict(self._document, **{ns: copy.deepcopy(section)})


@pytest.mark.asyncio
@pytest.mark.parametrize('late_settings', [False, True])
async def test_boot_default_model_has_serializable_live_settings(late_settings):
    ctx = Context()
    try:
        if not late_settings:
            await ctx.plugin(MemorySettings, {})
        owner = await ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-agent-default-model'),
                                 dict(provider='first', model='first-model'))
        if late_settings:
            await ctx.plugin(MemorySettings, {})
        settings = ctx.get('settings')
        section = next(row for row in settings.describe() if row['ns'] == 'agent-default-model')
        assert set(section['schema']) == {'uid', 'refs'}
        assert_json(section['schema'])
        json.dumps(section['schema'])
        service = ctx.get('agentDefaultModel')
        await service.saveSelection(dict(provider='second', model='second-model', reasoningEffort='high'))
        assert service.currentSelection() == dict(provider='second', model='second-model', reasoningEffort='high')
        await owner.dispose()
        assert ctx.get('agentDefaultModel') is None
        assert not any(row['ns'] == 'agent-default-model' for row in settings.describe())
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('strict_artifact', [False, True])
async def test_boot_commands_remote_serializes_and_owns_effects(strict_artifact):
    ctx = Context()
    try:
        await ctx.plugin(TypertRegistry)
        await ctx.plugin(SessionStore)
        await ctx.plugin(resolve_harness_plugin('@deepseek-ai/dsh-commands'))
        if strict_artifact:
            ctx.get('typert').register(read_generated_artifact('packages/interaction/commands/lib/typert.host.js'))
        agent = Agent(session=ctx.get('sessions').create('remote-command'), ctx=ctx, agent_id='remote-command')
        ctx.get('typert').lookups.register('agent', TypertLookupProvider(
            'agent', 'agentId', 'host#Agent', '@deepseek-ai/dsh-session/types#SessionId', lambda key: agent if key == agent.id else None))
        commands = ctx.get('commands')
        dispose = commands.register(dict(name='sample', description='Controlled command',
                                         input=dict(hint='<value>', images=True),
                                         handler=lambda invocation: dict(kind='success', text=invocation.rawInput)))
        remote = RemoteDispatcher(ctx)
        async def call(method, **args):
            return await remote.invoke(dict(namespace='commands', method=method, args=dict(agentId=agent.id, **args)))
        listed = await call('list')
        expected = [dict(name='sample', description='Controlled command', input=dict(hint='<value>', images=True))]
        assert listed == expected
        assert_json(listed)
        async def handler(endpoint, payload, signal):
            return dict(ok=True, value=await remote.invoke(dict(namespace='commands', method='list', args=payload['args'])))
        envelope = dict(type='client-request', rpcId='controlled-list', method='commands/list', payload=dict(args=dict(agentId=agent.id)))
        response = await rpc_fetch('/api', handler, dict(path='/api/commands/list', method='POST',
            headers={'content-type': 'application/json'}, body=json.dumps(envelope).encode('utf-8')))
        assert response['status'] == 200
        assert json.loads(response['body'])['result'] == dict(ok=True, value=expected)
        execution = await call('execute', line='/sample exact input', images=[])
        assert_json(execution)
        assert execution['result'] == dict(kind='success', text=' exact input')
        events = [event for event in agent.session.events if event['type'].startswith('command/')]
        assert [event['type'] for event in events] == ['command/run', 'command/done']
        assert all(event['data']['commandId'] == execution['commandId'] for event in events)
        assert await call('execute', line='/missing', images=[]) is UNDEFINED
        dispose()
        assert await call('list') == []
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [LlmError('Invalid controlled catalog', 'INVALID_CATALOG'),
                                  RuntimeError('Ordinary catalog failure')])
async def test_model_catalog_preserves_error_message_without_code_prefix(error):
    class Llm:
        def listProviders(self):
            return [dict(id='controlled', name='Controlled')]

        async def list_models(self, provider):
            raise error

    ctx = Context()
    ctx.set_service('llm', Llm())
    ctx.set_service('agentDefaultModel', SimpleNamespace(currentSelection=lambda: dict(provider='controlled', model='model')))
    try:
        catalog = await SessionController.modelCatalog(SimpleNamespace(ctx=ctx))
        assert catalog['failures'] == [dict(id='controlled', name='Controlled',
                                            message=getattr(error, 'message', str(error)))]
        assert catalog['groups'] == []
        assert catalog['routableProviders'] == ['controlled']
    finally:
        await ctx.fiber.dispose()
