"""Durable value preservation and refusal boundaries for the explicit v4 helpers."""
import copy
import json

import pytest

from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError
from dsh.session.format_v3_to_v4.tool_role import liftToolResult, assertV4ToolResultMessage
from dsh.session.format_v3_to_v4.sources import rewriteV3MessageSource
from dsh.session.format_v3_to_v4.content import migrateV3EventContent


def result():
    return dict(type='tool/result', seq=4, time=9, data=dict(message=dict(id='result', role='user',
        source=dict(kind='tool', callId='call'), content=[dict(type='tool-result', toolCallId='call', content=[])])))


@pytest.mark.parametrize('is_error', [False, True])
def test_lift_preserves_independent_extension_owners_and_writer_order(is_error):
    row = result()
    source = row['data']['message']['source']
    message = row['data']['message']
    wrapper = message['content'][0]
    message.update({'isError': 'historical', '__proto__': {'saved': 1}, 'constructor': 'outer'})
    wrapper.update({'isError': is_error, '__proto__': [2], 'constructor': 'inner'})
    before = copy.deepcopy(row)
    target = liftToolResult(row)
    lifted = target['data']['message']
    assert list(lifted)[:6] == ['role', 'source', 'toolCallId', 'content', 'isError', 'id']
    assert lifted['source'] is source and lifted['content'] is wrapper['content']
    assert lifted['plugin:message:isError'] == 'historical'
    assert lifted['plugin:message:__proto__'] == {'saved': 1}
    assert lifted['plugin:result:__proto__'] == [2]
    assert lifted['plugin:message:constructor'] == 'outer'
    assert lifted['plugin:result:constructor'] == 'inner'
    assert row == before
    assert json.loads(json.dumps(target)) == target
    assertV4ToolResultMessage(target)


@pytest.mark.parametrize('contents', [[None], [dict(type='plugin:test', arguments={'type': 'tool-result'})]])
def test_tool_lift_retains_opaque_content_for_later_native_admission(contents):
    row = result()
    row['data']['message']['content'][0]['content'] = contents
    assert liftToolResult(row)['data']['message']['content'] is contents


def test_nested_result_refused_before_any_source_mutation():
    row = result()
    row['data']['message']['content'][0]['content'] = [dict(type='tool-result', content=[])]
    before = copy.deepcopy(row)
    with pytest.raises(SessionFormatUnsupportedMigrationError, match='nested'):
        liftToolResult(row)
    assert row == before


@pytest.mark.parametrize('error', [None, 0, 1, 'true'])
def test_error_flags_do_not_coerce_json_values(error):
    row = result(); row['data']['message']['content'][0]['isError'] = error
    with pytest.raises(SessionFormatError, match='boolean'):
        liftToolResult(row)


def test_native_error_metadata_requires_explicit_error_result():
    row = liftToolResult(result())
    row['data']['error'] = None
    with pytest.raises(SessionFormatError, match='non-error'):
        assertV4ToolResultMessage(row)
    row['data']['message']['isError'] = True
    assertV4ToolResultMessage(row)


@pytest.mark.parametrize('plugin,role,kind', [
    ('@deepseek-ai/dsh-system-prompt', 'system', 'system-prompt'),
    ('@deepseek-ai/dsh-system-prompt', 'user', 'runtime-context'),
    ('tools-code-mode', 'user', 'ptc-mode'), ('compact', 'user', 'compact-checkpoint'),
    ('goal', 'user', 'goal'), ('plugin:unknown', 'user', 'plugin:plugin:unknown'),
    ('__proto__', 'user', 'plugin:__proto__'),
])
def test_producer_attribution_preserves_metadata_and_original_source(plugin, role, kind):
    original = dict(kind='plugin', plugin=plugin, payload={'opaque': 1})
    value = rewriteV3MessageSource(original, 3, role)
    assert value == dict(kind=kind, payload={'opaque': 1})
    assert value['payload'] is original['payload']
    assert original['kind'] == 'plugin' and original['plugin'] == plugin


def test_unknown_direct_producer_and_uninterpreted_payload_keep_identity():
    source = dict(kind='extension', plugin='still-opaque')
    assert rewriteV3MessageSource(source, 0, 'user') is source
    row = dict(type='extension/event', seq=0, time=1, data=dict(content=[dict(type='custom')]))
    assert migrateV3EventContent(row) is row


def test_content_conversion_is_shallow_and_does_not_reinterpret_tool_arguments():
    opaque = {'type': 'custom', 'deferLoading': True}
    row = dict(type='assistant/message', seq=3, time=4, data=dict(message=dict(content=[
        dict(type='tool-call', arguments=opaque), dict(type='custom', nested=opaque)])))
    before = copy.deepcopy(row)
    target = migrateV3EventContent(row)
    content = target['data']['message']['content']
    assert content[0] is row['data']['message']['content'][0]
    assert content[1]['type'] == 'plugin:custom'
    assert content[1]['nested'] is opaque
    assert row == before


@pytest.mark.parametrize('flag', [None, False, True])
def test_v4_only_tool_definition_field_refused_even_when_disabled(flag):
    row = dict(type='request/header', seq=0, time=1, data=dict(header=dict(tools=[dict(deferLoading=flag)])))
    with pytest.raises(SessionFormatUnsupportedMigrationError, match='only defined in V4'):
        migrateV3EventContent(row)
