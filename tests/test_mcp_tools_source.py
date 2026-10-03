import json
import base64
import copy
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from dsh.core.abort import AbortController
from dsh.attachment.error import AttachmentError
from dsh.mcp.tools import public_tool_name, sync_tools


ROOT = Path(__file__).resolve().parents[1]


class Execution:
    def __init__(self):
        self.signal = AbortController().signal


@pytest.mark.asyncio
async def test_actual_source_bridge_text_names_and_exact_execution_refusal(tmp_path):
    output = tmp_path / 'tools.json'
    environment = dict(os.environ, MCP_TOOLS_OUTPUT=str(output))
    subprocess.run([shutil.which('node'), '--expose-internals', str(ROOT / 'scripts/oracles/official/node_modules/vitest/vitest.mjs'),
        'run', '--config', str(ROOT / 'scripts/oracles/vitest.mcp-tools-probe.config.mts')],
        cwd=str(ROOT), env=environment, check=True, capture_output=True, timeout=60)
    rows = json.loads(output.read_text(encoding='utf-8'))
    assert len(rows) == 38
    for row in rows:
        if row['kind'] == 'name':
            assert public_tool_name('controlled', row['rawName']) == row['result']
            continue
        if row['kind'] == 'rich':
            assert await observe_rich(row) == row
            continue
        definitions = []
        class Tools:
            def register(self, definition):
                definitions.append(definition)
                return lambda: None
        class Context:
            def get(self, name):
                return Tools() if name == 'tools' else None
        class Client:
            async def request(self, packet, **kwargs):
                return {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]} if packet['method'] == 'tools/list' else row['value']
        disposers = await sync_tools(Client(), Context(), {'serverName': 'controlled'}, {})
        definition, execution = definitions[0], Execution()
        value = await definition['execute']({}, execution)
        fallback = definition['output']['render']({}, value)
        final = definition['finalizeContent'](execution, dict(value=value, content=fallback, isError=False))
        actual = dict(value=value, fallback=fallback)
        if final is not None:
            actual['final'] = final
        assert actual == {name: row[name] for name in ('value', 'fallback', 'final') if name in row}
        assert definition['finalizeContent'](execution, dict(value=value, content=fallback, isError=False)) is None
        for disposer in disposers.values():
            disposer()


async def observe_rich(row):
    scenario, definitions, trace = row['scenario'], [], []
    controller = AbortController()
    class Attachments:
        async def save_images(self, images):
            trace.append({'save': [{'data': base64.b64encode(image['data']).decode('ascii'),
                'mediaType': image['mediaType']} for image in images]})
            if scenario in ('admission', 'storage', 'unknown-code'):
                raise AttachmentError('controlled storage failure', {'admission': 'INVALID_IMAGE',
                    'storage': 'ATTACHMENT_WRITE_FAILED', 'unknown-code': 'OTHER'}[scenario])
            return [{'attachmentId': 'controlled-' + str(index), 'mediaType': 'image/png',
                'bytes': 3, 'width': 1, 'height': 1} for index in range(len(images))]
    class Llm:
        async def resolve_model_info(self, provider, model, signal):
            trace.append({'route': [provider, model], 'ownedSignal': signal is controller.signal})
            if scenario == 'unverified':
                raise RuntimeError('controlled route failure')
            if scenario == 'abort-resolve':
                controller.abort()
            return {} if scenario == 'missing-modalities' else {
                'inputModalities': ['text'] if scenario == 'text-model' else ['text', 'image']}
    class Tools:
        def register(self, definition):
            definitions.append(definition)
            return lambda: None
    class Context:
        def get(self, name):
            return {'tools': Tools(), 'attachments': None if scenario == 'no-attachments' else Attachments(),
                'llm': None if scenario == 'no-llm' else Llm()}.get(name)
    class Client:
        async def request(self, packet, **kwargs):
            return {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]} if packet['method'] == 'tools/list' else row['value']
    class Session:
        def request_header(self):
            return {'config': {'provider': 'header', 'model': 'vision'}} if scenario == 'header-route' else None
    class Agent:
        session = Session()
        options = {'provider': 'options', 'model': 'fallback'}
    execution, second = Execution(), Execution()
    execution.signal = second.signal = controller.signal
    if scenario != 'no-agent':
        execution.agent = second.agent = Agent()
    if scenario == 'aborted':
        controller.abort()
    disposers = await sync_tools(Client(), Context(), {'serverName': 'controlled'}, {})
    definition = definitions[0]
    value = await definition['execute']({}, execution)
    fallback = definition['output']['render']({}, value)
    result = {'value': copy.deepcopy(value), 'content': copy.deepcopy(fallback), 'isError': scenario == 'result-error'}
    if scenario == 'replaced-value':
        result['value']['structuredContent']['flag'] = True
    if scenario == 'boolean-number':
        result['value']['structuredContent']['flag'] = 0
    if scenario == 'changed-content':
        result['content'][0]['text'] = 'changed'
    if scenario == 'concurrent':
        await definition['execute']({}, second)
    final = definition['finalizeContent'](second if scenario == 'foreign-execution' else execution, result)
    repeated = definition['finalizeContent'](execution, {'value': value, 'content': fallback, 'isError': False})
    actual = {'kind': 'rich', 'scenario': scenario, 'value': value, 'fallback': fallback, 'trace': trace}
    for name, projection in [('final', final), ('repeated', repeated)]:
        if projection is not None:
            actual[name] = projection
    if scenario == 'concurrent':
        actual['concurrent'] = definition['finalizeContent'](second, {'value': value, 'content': fallback, 'isError': False})
    for disposer in disposers.values():
        disposer()
    return actual
