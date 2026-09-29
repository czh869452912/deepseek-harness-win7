"""Settings and plugin inventory acceptance through the shipped Web composition."""
import os

import pytest

from canonical_web_fixture import web_context, close_web_context
from dsh.presets.mount import standing_mount_for, inactive_rows
from dsh.typert.dispatch import RemoteDispatcher


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
        shell = await call('settings', 'update', ns='shell', patch={'timeoutMs': 121000},
                           expectedRevision=rows['shell']['revision'])
        assert shell['value']['timeoutMs'] == 121000
        await call('settings', 'update', ns='agent-presets', patch={'default': 'minimal'},
                   expectedRevision=rows['agent-presets']['revision'])

        inventory = (await call('pluginInventory', 'list'))['entries']
        by_id = {row['entryId']: row for row in inventory}
        # These are disabled HOST entries in the unchanged upstream bundle.
        for entry in ('hmr', 'tool-fs', 'tool-pwsh', 'tool-bash'):
            assert by_id['include:' + entry]['enabled'] is False
            assert by_id['include:' + entry]['fiberPhase'] is None
        assert by_id['include:client-hmr']['enabled'] is True
        assert by_id['include:client-hmr']['fiberPhase'] == 'active'

        await call('session', 'create', request=dict(cwd=str(tmp_path), sessionId='standard-tools', agentPreset='standard'))
        agent = ctx.get('agents').get('standard-tools')
        names = {tool.name for tool in ctx.get('tools').list_tools(scope=agent.ctx)}
        assert {'read', 'write', 'edit', 'glob', 'grep', 'skill', 'todo_write', 'subagent'} <= names
        assert ('pwsh' if os.name == 'nt' else 'bash') in names
        mount = standing_mount_for(agent.ctx)
        assert mount is not None and not inactive_rows(mount.tree)
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
        assert rows['shell']['value']['timeoutMs'] == 121000
        assert rows['agent-presets']['value']['default'] == ctx.get('agentPresets').default_id == 'minimal'
    finally:
        await close_web_context(ctx)
