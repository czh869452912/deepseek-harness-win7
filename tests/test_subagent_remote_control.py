import pytest
from dsh.core.abort import AbortController
from dsh.typert.remote import TypertRemoteFailure, remote_methods
from dsh.session.projections import SessionProjectionsPlugin
from dsh.subagent.projections import IDENTITY
from test_subagent_continuation import mounted, retired


@pytest.mark.asyncio
async def test_remote_prompt_preserves_browser_source_and_named_failure(tmp_path):
    ctx, _, parent, manager = await mounted(tmp_path)
    service, signal = manager.host, AbortController().signal
    service.continuations = manager
    await ctx.plugin(SessionProjectionsPlugin)
    ctx.get('sessionProjections').register(IDENTITY)
    try:
        await manager.start(dict(provider='spawn', label='worker', childId='worker', request=dict(parent=parent.agent, prompt='first')))
        await retired(manager, 'worker')
        await parent.agent.when_idle()
        request = dict(parentSessionId='parent', childSessionId='worker', mode='continuable', requestId='browser-request',
                       clientTimeZone='Asia/Shanghai', content=[dict(type='text', text='browser followup')])
        receipt = await service.prompt(request, signal)
        await retired(manager, 'worker')
        await parent.agent.when_idle()
        observation = await ctx.get('sessionQuery').observeSession('worker')
        message = next(event['data'] for event in observation.events if event['type'] == 'user/message' and event['data']['id'] == receipt['messageId'])
        assert message['source'] == dict(kind='user', rpcId='browser-request', clientTimeZone='Asia/Shanghai')
        observation.dispose()
        catalog = await service.remoteExportList('parent', signal)
        assert catalog['parentAvailable'] and catalog['entries'][0]['activity'] == 'inactive'
        with pytest.raises(TypertRemoteFailure) as error:
            await service.prompt(dict(request, clientTimeZone='Invalid/Place'), signal)
        assert error.value.failure['code'] == 'invalid-time-zone'
        assert service.interruptByParent('absent', 'parent', 'continuable') == {'accepted': True}
        with pytest.raises(TypertRemoteFailure) as error:
            service.interruptByParent('absent', '', 'continuable')
        assert error.value.failure['code'] == 'bad-request'
        exports = {row.get('exportName', row['method']) for row in remote_methods(service)}
        assert exports == {'list', 'prompt', 'interruptByParent'}
    finally:
        await manager.drain()
        await parent.dispose()
        await ctx.fiber.dispose()
