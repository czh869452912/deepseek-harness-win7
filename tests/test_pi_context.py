import copy
import json
from pathlib import Path

import pytest

from dsh.llm.llm_service import LlmError
from dsh.llm.pi_context import to_pi_context, to_pi_context_with_images


FIXTURES = json.loads((Path(__file__).resolve().parents[1] / 'scripts/oracles/pi-fixtures.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
async def test_image_budget_does_not_rewrite_history_and_reads_each_identity_once():
    fixture = next(row for row in FIXTURES if row['id'] == 'context-duplicate-image')
    options = copy.deepcopy(fixture['options'])
    before = copy.deepcopy(options)
    reads = []

    class Store:
        def read_image_request(self, ref, policy, signal):
            reads.append(ref['attachmentId'])
            return dict(data=b'abcdef', bytes=6, width=2, height=2, mediaType='image/png')

    result = await to_pi_context_with_images(options, Store(), lambda ref: None, 8)
    assert len(reads) == 1
    content = result['messages'][0]['content']
    assert sum(block['type'] == 'image' for block in content) == 1
    assert 'omitted to fit request' in content[0]['text']
    assert options == before


@pytest.mark.asyncio
async def test_unsupported_image_role_is_rejected_before_budget_or_store_access():
    fixture = next(row for row in FIXTURES if row['id'] == 'context-image-role-assistant')

    class Store:
        def read_image_request(self, *args):
            pytest.fail('unsupported role must not read attachment')

    with pytest.raises(LlmError) as error:
        await to_pi_context_with_images(fixture['options'], Store(), lambda ref: None, 0)
    assert error.value.code == 'UNSUPPORTED_CONTENT'


def test_tool_result_keeps_originating_name_order_and_empty_output_marker():
    fixture = next(row for row in FIXTURES if row['id'] == 'context-tool-roundtrip')
    result = to_pi_context(fixture['options'])
    assert result['systemPrompt'] == 'system'
    assert [message['role'] for message in result['messages']] == ['user', 'assistant', 'user', 'toolResult']
    assert result['messages'][-1]['toolName'] == 'calculate'
    assert result['messages'][-1]['content'] == [dict(type='text', text='onetwo')]
    fixture = next(row for row in FIXTURES if row['id'] == 'context-empty-results')
    result = to_pi_context(fixture['options'])
    assert result['messages'][0]['toolName'] == 'unknown'
    assert result['messages'][0]['isError'] is True
    assert result['messages'][0]['content'][0]['text'] == '(no output)'
    assert 'tools' not in result
