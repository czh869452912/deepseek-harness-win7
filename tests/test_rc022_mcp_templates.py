import asyncio
import copy

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.credentials.local_current import CurrentCredentialsLocalPlugin as CredentialsLocalPlugin
from dsh.mcp.credentials_current import McpTemplateBinding
from dsh.mcp.diagnostic_current import McpLocalError
from scripts.rc022_mcp_templates_probe import observe


def test_credential_grammar_resolution_and_redaction_corpus():
    rows=asyncio.run(observe())
    assert len(rows)==25
    stdio=next(row for row in rows if row.get('name')=='stdio-order-memo-rotation')
    assert stdio['refs']==['A','B','C']
    assert stdio['attempts'][0]['calls']==['B','A','C']
    assert stdio['attempts'][1]['calls']==['B','A','C']
    assert 'rotated%20%2F' not in stdio['attempts'][1]['redacted']


@pytest.mark.asyncio
async def test_real_local_credentials_provider_rotates_without_expanding_stored_config(tmp_path):
    ctx=Context()
    try:
        fiber=await ctx.plugin(CredentialsLocalPlugin(dict(path=str(tmp_path/'credentials.yaml'))))
        provider=ctx.credentials;await provider.set('RC022_MCP_SYNTHETIC','first/token')
        config=dict(transport='streamable-http',serverName='local',url='http://fixture',headers={'Authorization':'Bearer ${credential:RC022_MCP_SYNTHETIC}'},expandTemplates=True)
        raw=copy.deepcopy(config);binding=McpTemplateBinding(ctx,config);signal=AbortController().signal
        assert (await binding.resolve(signal))['headers']['Authorization']=='Bearer first/token'
        await provider.set('RC022_MCP_SYNTHETIC','next/token')
        assert (await binding.resolve(signal))['headers']['Authorization']=='Bearer next/token'
        assert config==raw
        assert binding.redact('first/token first%2Ftoken next/token next%2Ftoken')=='[redacted] [redacted] [redacted] [redacted]'
        await fiber.dispose()
        with pytest.raises(McpLocalError,match='require a credentials provider'):await binding.resolve(signal)
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_binding_caller_keeps_resolved_value_in_redaction_set():
    ctx=Context();entered=asyncio.Event();held=asyncio.get_running_loop().create_future()
    class Provider:
        async def resolve(self,ref):entered.set();await held;return dict(value='late/controlled')
    ctx.set_service('credentials',Provider())
    binding=McpTemplateBinding(ctx,dict(transport='streamable-http',serverName='late',url='${credential:TOKEN}',headers={},expandTemplates=True))
    resolving=asyncio.create_task(binding.resolve(AbortController().signal))
    try:
        await entered.wait();resolving.cancel()
        with pytest.raises(asyncio.CancelledError):await resolving
        assert not held.cancelled()
        held.set_result(None)
        for _ in range(6):await asyncio.sleep(0)
        assert binding.redact('late/controlled late%2Fcontrolled')=='[redacted] [redacted]'
    finally:await ctx.fiber.dispose()
