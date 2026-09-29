import asyncio

import pytest

from dsh.api.workspace import WorkspaceController
from dsh.core.abort import AbortController
from dsh.typert.registry import TypertRegistry
from dsh.typert.artifact import read_generated_artifact
from dsh.typert.dispatch import RemoteDispatcher
from test_storage_and_workspace import workspace_context


@pytest.mark.asyncio
async def test_workspace_generated_remote_committed_feed_and_reconnect(tmp_path):
    ctx, registry = await workspace_context(tmp_path)
    await ctx.plugin(TypertRegistry)
    await ctx.plugin(WorkspaceController)
    ctx.get('typert').register(read_generated_artifact('packages/api/workspace-controller/lib/typert.host.js'))
    dispatcher = RemoteDispatcher(ctx)
    controller = ctx.get('workspaceController')
    signal = AbortController()
    feed = controller.follow(signal.signal)
    async def next_frame():
        return await asyncio.wait_for(feed.__anext__(), 2)
    async def call(method, request):
        return await dispatcher.invoke(dict(namespace='workspace', method=method, args={'request': request}))
    try:
        assert await next_frame() == dict(type='baseline', value=dict(items=[], archivedSessionIds=[]))
        result = await call('create', {'path': str(tmp_path)})
        workspace = result['workspace']
        identity = workspace['workspaceId']
        assert result['created']
        assert await next_frame() == dict(type='upsert', workspace=workspace)
        assert await next_frame() == dict(type='order', workspaceIds=[identity])
        assert not (await call('create', {'path': str(tmp_path)}))['created']
        renamed = await call('rename', {'workspaceId': identity, 'title': 'Renamed'})
        assert await next_frame() == dict(type='upsert', workspace=renamed['workspace'])
        assert registry.get(identity).title == 'Renamed'
        await feed.aclose()
        feed = controller.follow(signal.signal)
        assert (await next_frame())['value']['items'] == [renamed['workspace']]
        await call('delete', {'workspaceId': identity})
        assert await next_frame() == dict(type='order', workspaceIds=[])
        assert await next_frame() == dict(type='remove', workspaceId=identity)
        signal.abort()
        with pytest.raises(StopAsyncIteration):
            await next_frame()
    finally:
        await feed.aclose()
        await ctx.fiber.dispose()
