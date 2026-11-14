"""V4 refusal guards distinguish durable syntax from opaque extension values."""
import copy

import pytest

from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError
from dsh.session.format_v3_to_v4.developer import assertV4DeveloperData
from dsh.session.format_v3_to_v4.message_sources import assertV4MessageSources, assertV4SourceRowAdmission
from dsh.session.format_v3_to_v4.retired_syntax import assertV4RetiredSyntax
from dsh.session.format_v3_to_v4.system_message import assertV4SystemMessageFields


def developer(content, **extra):
    return dict(type='developer/message', data=dict(turn=1, step=1, message=dict(
        id='d', role='developer', source=dict(kind='tools'), content=content), **extra))


def test_tool_addition_requires_header_reference_but_removal_omits_it():
    addition = developer([dict(type='tool-addition', toolName='new')], headerSeq=0)
    before = copy.deepcopy(addition)
    assertV4DeveloperData(addition)
    assert addition == before
    del addition['data']['headerSeq']
    with pytest.raises(SessionFormatError, match='headerSeq'):
        assertV4DeveloperData(addition)
    removal = developer([dict(type='tool-removal', toolName='old')])
    assertV4DeveloperData(removal)
    removal['data']['headerSeq'] = 0
    with pytest.raises(SessionFormatError, match='omit headerSeq'):
        assertV4DeveloperData(removal)


@pytest.mark.parametrize('value', [None, False, 0, 'true'])
def test_deferred_tool_marker_requires_literal_true(value):
    row = dict(type='request/header', data=dict(header=dict(tools=[dict(deferLoading=value)])))
    with pytest.raises(SessionFormatError, match='deferLoading must be true'):
        assertV4DeveloperData(row)


@pytest.mark.parametrize('kind', ['user/message', 'assistant/message', 'tool/result'])
def test_developer_role_cannot_enter_an_ordinary_message_slot(kind):
    message = developer([])['data']['message']
    row = dict(type=kind, data=message if kind == 'user/message' else dict(message=message))
    with pytest.raises(SessionFormatError, match='must occur together'):
        assertV4DeveloperData(row)


def test_physical_source_admission_refuses_retired_source_without_hiding_recoverable_corruption():
    row = dict(type='user/message', data=dict(source=dict(kind='plugin', plugin='goal')))
    with pytest.raises(SessionFormatError, match='producer-owned'):
        assertV4SourceRowAdmission(row)
    row['data']['source'] = None
    assertV4SourceRowAdmission(row)
    with pytest.raises(SessionFormatError, match='producer-owned'):
        assertV4MessageSources(row)
    row['data']['source'] = dict(kind='plugin:goal', extra={'retained': True})
    before = copy.deepcopy(row)
    assertV4MessageSources(row)
    assert row == before


def test_developer_source_is_admitted_by_the_developer_guard():
    row = developer([])
    row['data']['message']['source'] = dict(kind='plugin', plugin='tools')
    assertV4SourceRowAdmission(row)
    with pytest.raises(SessionFormatError, match='producer-owned'):
        assertV4DeveloperData(row)


@pytest.mark.parametrize('ignorable', [None, False, 0, 1])
def test_retired_ptc_event_requires_literal_ignorable_true(ignorable):
    row = dict(type='tool/code-dispatch', ignorable=ignorable, data={})
    with pytest.raises(SessionFormatUnsupportedMigrationError, match='retired event'):
        assertV4RetiredSyntax(row)
    row['ignorable'] = True
    assertV4RetiredSyntax(row)


def test_retired_syntax_checks_declared_slots_and_leaves_tool_arguments_opaque():
    wrapper = dict(type='tool-result', content=[])
    row = dict(type='assistant/message', seq=2, data=dict(message=dict(content=[
        dict(type='tool-call', arguments=wrapper), dict(type='plugin:x', value=wrapper)])))
    before = copy.deepcopy(row)
    assertV4RetiredSyntax(row)
    assert row == before
    row['data']['stream'] = [dict(type='chunk', chunk=dict(type='block-start', blockType='tool-result'))]
    with pytest.raises(SessionFormatError, match='released tool-result wrapper'):
        assertV4RetiredSyntax(row)


@pytest.mark.parametrize('count', [False, True, -1, 1.5, 9007199254740992])
def test_system_dimensions_and_turn_counts_do_not_coerce_numbers(count):
    row = dict(type='system/message', data=dict(turn=count, step=1, message=dict(id='s', role='system', content=[])))
    with pytest.raises(SessionFormatError):
        assertV4SystemMessageFields(row)


def test_system_image_validates_known_fields_and_preserves_extension_content():
    image = dict(type='image', attachment=dict(attachmentId='a', mediaType='image/png', bytes=0,
        width=1, height=2, originalDimensions=dict(width=1, height=2), name=''))
    row = dict(type='system/message', data=dict(turn=1, step=1, message=dict(id='s', role='system',
        content=[image, dict(type='plugin:opaque', value=dict(type='tool-result'))])))
    before = copy.deepcopy(row)
    assertV4SystemMessageFields(row)
    assert row == before
    image['attachment']['width'] = 0
    with pytest.raises(SessionFormatError, match='width must be positive'):
        assertV4SystemMessageFields(row)
