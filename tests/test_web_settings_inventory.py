"""Settings and plugin inventory acceptance through the shipped Web composition."""
import os
import asyncio

import pytest

from canonical_web_fixture import web_context, close_web_context
from dsh.typert.dispatch import RemoteDispatcher
from dsh.typert.remote import RemoteError


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['deepseek-base', 'retry-union', 'ordinary-provider', 'locale-pattern'])
async def test_source_settings_schema_facts_survive_canonical_web_boot(tmp_path, case):
    ctx = await web_context(tmp_path / 'home')
    try:
        directory = await RemoteDispatcher(ctx).invoke(dict(namespace='settings', method='describe', args={}))
        rows = {row['ns']: row for row in directory['namespaces']}
        if case == 'deepseek-base':
            # The pinned provider exports Config; Loader defaults are public
            # Settings.base facts, before a user writes any overrides.
            base = rows['llm-deepseek']['base']
            assert base['apiKeyEnv'] == 'DEEPSEEK_API_KEY'
            assert base['maxTokens'] == 256000
            assert base['streamIdleTimeoutMs'] == 300000
            assert base['fileExpiresAfterSeconds'] == 604800
            assert [model['id'] for model in base['models']] == [
                'deepseek-flash', 'deepseek-v4-pro']
            assert 'baseURL' not in base
        elif case == 'retry-union':
            # Current forms expose only volatile Config fields. Preserve the
            # exact retry union and shared backoff relation within that graph.
            deepseek = rows['llm-deepseek']['schema']
            root = deepseek['refs'][str(deepseek['uid'])]
            retry_uid = str(root['dict']['retryPolicy'])
            retry = deepseek['refs'][retry_uid]
            assert retry['type'] == 'union' and len(retry['list']) == 2
            modes = [deepseek['refs'][str(uid)] for uid in retry['list']]
            assert modes[0]['dict']['backoff'] == modes[1]['dict']['backoff']
        elif case == 'ordinary-provider':
            assert rows['llm-pi-ai']['value']['providers'] == {}
            inventory = await RemoteDispatcher(ctx).invoke(dict(namespace='pluginInventory',method='list',args={}))
            entry = next(row for row in inventory['entries'] if row['entryId']=='include:llm-pi-ai')
            assert entry['enabled'] and entry['fiberPhase']=='active'
        else:
            schema = rows['locale']['schema']
            root = schema['refs'][str(schema['uid'])]
            preference = schema['refs'][str(root['dict']['preference'])]
            assert preference['meta']['pattern'] == dict(
                source=r'^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$', flags='')
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_issue11_live_settings_and_archived_preferences(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    (home / 'settings.yaml.imported').write_text(
        'ui-developer-tools:\n  enabled: false\nui-chat:\n  transcriptView: expanded\n'
        'ui-conversation:\n  busyEnter: steer\nui-theme:\n  preference: light\n', encoding='utf-8')
    ctx = await web_context(home)
    try:
        remote = RemoteDispatcher(ctx)

        async def update(ns, **patch):
            return await remote.invoke(dict(namespace='settings', method='update', args=dict(ns=ns, patch=patch)))

        receipt = home / 'profiles' / 'web' / 'legacy-settings-issue11.sha256'

        async def wait_for_recovery():
            while not receipt.is_file():
                await asyncio.sleep(0.05)

        # Recovery serializes three real settings writes, each with a Loader
        # reload. Poll only its receipt and allow those writes on a busy host.
        await asyncio.wait_for(wait_for_recovery(), 60)
        rows = {row['ns']: row for row in ctx.settings.describe()}
        assert rows['ui-settings']['value'] == {'enabled': False}
        assert not rows['ui-settings']['autoGenerate']
        assert rows['ui-chat']['value']['transcriptView'] == 'expanded'
        assert rows['ui-conversation']['value']['busyEnter'] == 'steer'
        assert 'preference' not in rows['ui-theme']['user']
        await update('ui-settings', enabled=True)
        await update('ui-chat', linkOpening='new-tab', performanceUsage='compact')
        await update('agent-loop', maxParallelToolCalls=2)
        assert ctx.agentLoop.config['maxParallelToolCalls'] == 2

        catalog, custom = 'openai', 'issue11-local'
        await update('llm-pi-ai', providers={catalog: {'models': [{'id': 'gpt-4o'}]},
            custom: {'api': 'openai-completions', 'baseURL': 'http://127.0.0.1:1/v1', 'models': [{'id': 'local'}]}})
        assert 'local' in {m['id'] for m in await ctx.llm.listModels(custom)}
        with pytest.raises(RemoteError) as rejected:
            await update('llm-pi-ai', providers={custom: {'baseURL': ''}})
        assert rejected.value.code == 'settings/rejected'
        assert 'local' in {m['id'] for m in await ctx.llm.listModels(custom)}
    finally:
        await close_web_context(ctx)

    ctx = await web_context(home)
    try:
        rows = {row['ns']: row for row in ctx.settings.describe()}
        assert rows['ui-settings']['value']['enabled'] is True
        assert rows['ui-chat']['value']['linkOpening'] == 'new-tab'
        assert ctx.agentLoop.config['maxParallelToolCalls'] == 2
        assert 'local' in {m['id'] for m in await ctx.llm.listModels('issue11-local')}
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_web_settings_persist_and_preset_tools_remain_available(tmp_path):
    home = tmp_path / 'home'
    ctx = await web_context(home)
    try:
        remote = RemoteDispatcher(ctx)

        async def call(namespace, method, **args):
            return await remote.invoke(dict(namespace=namespace, method=method, args=args))

        directory = await call('settings', 'describe')
        rows = {row['ns']: row for row in directory['namespaces']}
        shell = await call('settings', 'update', ns='pwsh-sandbox', patch={'timeoutMs': 121000},
                           expectedRevision=rows['pwsh-sandbox']['revision'])
        assert shell['value']['timeoutMs'] == 121000
        await call('settings', 'update', ns='agent-preset-registry', patch={'selectedDefault': 'minimal'},
                   expectedRevision=rows['agent-preset-registry']['revision'])

        inventory = (await call('pluginInventory', 'list'))['entries']
        by_id = {row['entryId']: row for row in inventory}
        # These are disabled HOST entries in the unchanged upstream bundle.
        for entry in ('tool-fs', 'tool-pwsh', 'tool-bash'):
            assert by_id['include:' + entry]['enabled'] is False
            assert by_id['include:' + entry]['fiberPhase'] is None
        assert by_id['include:client-hmr']['enabled'] is True
        assert by_id['include:client-hmr']['fiberPhase'] == 'active'
        assert by_id['include:hmr']['enabled'] is True
        assert by_id['include:hmr']['fiberPhase'] == 'active'

        await call('session', 'create', request=dict(cwd=str(tmp_path), sessionId='standard-tools', agentPreset='standard'))
        agent = ctx.get('agents').get('standard-tools')
        names = {tool.name for tool in ctx.get('tools').list_tools(scope=agent.ctx)}
        assert {'read', 'write', 'edit', 'glob', 'grep', 'skill', 'todo_write', 'subagent'} <= names
        assert ('pwsh' if os.name == 'nt' else 'bash') in names
        compositions = ctx.get('agentPresets').inspectCompositions(agent.ctx)
        assert len(compositions) == 1 and compositions[0]['id'] == 'standard'
        assert compositions[0]['modules'] and not compositions[0]['leakedServices']
        # Upstream inventory enumerates the host Loader only; preset subtrees
        # are audited by their own mount, not silently enabled in the host.
        assert not next(row for row in (await call('pluginInventory', 'list'))['entries']
                        if row['entryId'] == 'include:tool-fs')['enabled']
    finally:
        await close_web_context(ctx)

    ctx = await web_context(home)
    try:
        directory = await RemoteDispatcher(ctx).invoke(dict(namespace='settings', method='describe', args={}))
        rows = {row['ns']: row for row in directory['namespaces']}
        assert rows['pwsh-sandbox']['value']['timeoutMs'] == 121000
        assert rows['agent-preset-registry']['value']['selectedDefault'] == ctx.get('agentPresets').defaultId == 'minimal'
    finally:
        await close_web_context(ctx)
