import base64
import copy
import io
import json
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from dsh.attachment.local import LocalAttachmentStore
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.session import Session
from dsh.core.tools import ToolExecutionInput, ToolsService
from dsh.llm.llm_deepseek import DeepSeekAdapter
from dsh.llm.llm_service import LLMService
from dsh.mcp.tools import sync_tools
from dsh.mcp.transport import StdioMcpTransport
from test_deepseek_image_journey import endpoint


@pytest.mark.asyncio
async def test_real_stdio_image_tool_finalizes_durable_refs_and_cold_model_request(tmp_path, endpoint):
    url, state = endpoint
    image_output = io.BytesIO()
    Image.new('RGB', (20, 20), 'red').save(image_output, 'PNG')
    data = image_output.getvalue()
    raw_content = [{'type': 'text', 'text': 'before'}, {'type': 'image', 'mimeType': 'image/png',
        'data': base64.b64encode(data).decode('ascii')}, {'type': 'text', 'text': 'after'}]
    reply = {'content': raw_content, 'structuredContent': {'flag': False}}
    payload = tmp_path / 'reply.json'
    payload.write_text(json.dumps(reply), encoding='utf-8')
    server = tmp_path / 'server.py'
    server.write_text('''import json,sys
with open(sys.argv[1],encoding="utf-8") as stream:
    result=json.load(stream)
for line in sys.stdin:
    packet=json.loads(line)
    if "id" not in packet:
        continue
    method=packet.get("method")
    if method=="initialize":
        value={"protocolVersion":"2025-11-25","capabilities":{"tools":{}},"serverInfo":{"name":"image","version":"1"}}
    elif method=="tools/list":
        value={"tools":[{"name":"image","inputSchema":{"type":"object"}}]}
    else:
        value=result
    print(json.dumps({"jsonrpc":"2.0","id":packet["id"],"result":value}),flush=True)
''', encoding='utf-8')
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([
        {'source': 'process', 'values': {'DEEPSEEK_API_KEY': 'local-only'}}]))
    await ctx.plugin(LocalAttachmentStore, config={'dshHome': str(tmp_path)})
    tools, llm = ToolsService(ctx), LLMService(ctx)
    ctx.set_service('tools', tools)
    ctx.set_service('llm', llm)
    adapter = DeepSeekAdapter(ctx, {'baseURL': url, 'models': [{'id': 'vision', 'inputModalities': ['text', 'image']}]})
    llm.register_adapter(['deepseek-official'], adapter)
    client = StdioMcpTransport(sys.executable, [str(server), str(payload)])
    disposers = {}
    try:
        await client.connect()
        disposers = await sync_tools(client, ctx, {'serverName': 'owned'}, {})
        agent = SimpleNamespace(ctx=ctx, session=Session.create('controlled', ctx=ctx),
            options={'provider': 'deepseek-official', 'model': 'vision'})
        result = await tools.execute(ToolExecutionInput('image-call', 'mcp__owned__image', {},
            agent=agent, signal=AbortController().signal))
        assert not result.is_error and result.value == reply
        assert [block['type'] for block in result.content] == ['text', 'image', 'text']
        reference = result.content[1]['attachment']
        assert ctx.get('attachments').read_image(reference)['data'] == data
        assert 'data' not in result.content[1]
        cold_store = LocalAttachmentStore(config={'dshHome': str(tmp_path)})
        assert cold_store.read_image(reference)['data'] == data
        ctx.set_service('attachments', cold_store)
        messages = [{'role': 'user', 'content': [{'type': 'tool-result', 'toolCallId': 'image-call',
            'content': copy.deepcopy(result.content)}]}]
        original = copy.deepcopy(messages)
        prepared = await llm.prepare_adapter_call('deepseek-official', 'vision')
        chunks = [chunk async for chunk in prepared['stream']({'model': 'vision', 'messages': messages})]
        assert chunks[-1]['type'] == 'finish'
        assert state['uploads'] == [data] and len(state['chats']) == 1
        assert messages == original and result.value == reply
    finally:
        for disposer in disposers.values():
            disposer()
        await client.close()
        await adapter.close()
        await ctx.fiber.dispose()
    assert not tools.has_tool('mcp__owned__image')
    assert client.proc.returncode is not None and not client._pending
