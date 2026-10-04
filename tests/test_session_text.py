import re

import pytest

from dsh.session.session_query import compile_session_text_filter, extract_session_event_text, SessionQueryError
from dsh.session.text import trim_text, verify_case_folding
from dsh.session.query_engine import SqliteSessionQueryEngine
from dsh.cordis.context import Context
from dsh.core.session import SessionHeader, Session, SessionPlugin
from test_session_live_persistence import backend, mount
from test_prepared_persistence import persisted


@pytest.mark.parametrize('left,right', [('\u0412', '\u1c80'), ('\ua7cb', '\u0264'), ('\U00010d50', '\U00010d70'),
                                     ('\u1e9e', '\xdf'), ('s', '\u017f'), ('k', '\u212a'), ('\u0392', '\u03d0')])
def test_literal_simple_case_equivalents_match_in_both_directions(left, right):
    assert compile_session_text_filter(left).search(right)
    assert compile_session_text_filter(right).search(left)


@pytest.mark.parametrize('left,right', [('\xdf', 'ss'), ('\u0130', 'i'), ('\u0131', 'I'), ('é', 'e\u0301'), ('a', 'b')])
def test_literal_matching_refuses_full_fold_turkic_and_normalization(left, right):
    assert not compile_session_text_filter(left).search(right)
    assert not compile_session_text_filter(right).search(left)


@pytest.mark.parametrize('text,document,expected', [('\ud83d\ude00', '😀', True), ('😀', '\ud83d\ude00', True),
    ('\ud83d', '😀', False), ('\ud83d', '\ud83d\ude00', False), ('\ude00', '😀', False),
    ('\ude00', '\ud83d\ude00', False), ('\ud83d', '\ud83d', True), ('\ude00', '\ude00', True)])
def test_literal_unicode_mode_preserves_utf16_scalar_boundaries(text, document, expected):
    assert bool(compile_session_text_filter(text).search(document)) is expected


@pytest.mark.parametrize('character', ['\t', '\n', '\r', ' ', '\xa0', '\u1680', '\u2000', '\u200a',
                                     '\u2028', '\u2029', '\u202f', '\u205f', '\u3000', '\ufeff'])
def test_ecmascript_whitespace_is_trimmed_joined_and_refused_when_empty(character):
    assert trim_text(character + 'value' + character) == 'value'
    assert compile_session_text_filter('a b').search('A' + character + 'B')
    with pytest.raises(SessionQueryError) as error:
        compile_session_text_filter(character)
    assert error.value.code == 'SESSION_QUERY_INVALID_FILTER'
    assert extract_session_event_text(dict(type='user/message', data=dict(content=[dict(type='text', text=character + 'value' + character)]))) == 'value'


@pytest.mark.parametrize('character', ['\x1c', '\x1d', '\x1e', '\x1f', '\x85', '\u180e', '\u200b', '\u2060'])
def test_other_python_whitespace_remains_literal_and_semantic(character):
    assert trim_text(character + 'value' + character) == character + 'value' + character
    assert not compile_session_text_filter('a b').search('A' + character + 'B')
    assert compile_session_text_filter(character).search(character)
    assert extract_session_event_text(dict(type='user/message', data=dict(content=[dict(type='text', text=character + 'value' + character)]))) == character + 'value' + character


def test_literal_regex_operators_and_nul_are_data():
    pattern = compile_session_text_filter('[.*+?^${}()|\\]')
    assert isinstance(pattern, re.Pattern)
    assert pattern.search('prefix [.*+?^${}()|\\] suffix')
    assert not pattern.search('prefix anything suffix')
    assert compile_session_text_filter('a\0b').search('A\0B')


@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_missing_or_changed_case_folding_data_is_refused(tmp_path, damage):
    data = tmp_path / 'CaseFolding.txt'
    if damage == 'changed':
        data.write_text('changed Unicode mapping', encoding='utf-8')
    with pytest.raises((FileNotFoundError, RuntimeError)):
        verify_case_folding(data)


@pytest.mark.asyncio
@pytest.mark.parametrize('identities', [('é', 'e\u0301'), ('e\u0301', 'é')])
async def test_corpus_and_lineage_preserve_equal_collation_insertion_order(identities):
    context = Context()
    await context.plugin(SessionPlugin)
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='never'))
    try:
        root = SessionHeader('root', created_at=0)
        context.get('sessions').enter(Session.create(root.id, [], root))
        for identity in identities:
            header = SessionHeader(identity, created_at=1, parent_session='root')
            context.get('sessions').enter(Session.create(identity, [], header))
        assert [record['header'].id for record in await query.listSessions()] == list(identities) + ['root']
        trace = await query.traceSession('root')
        assert [child['session']['header'].id for child in trace['descendants']] == list(identities)
    finally:
        await query.close()
        await context.fiber.dispose()


@pytest.mark.asyncio
async def test_canonical_durable_text_filters_repeat_after_context_restart(backend):
    context, _, persistence = await persisted(backend)
    event = dict(type='user/message', seq=2, time=3, surfaceOp='append', data=dict(id='unicode-message', role='user',
                 content=[dict(type='text', text='\ufeff \u1c80 \u0264 \U00010d70 \ufeff')], source=dict(kind='user')))
    await persistence.append('s', [event])
    try:
        query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='never'))
        try:
            documents = await query.filterEvents('s', [dict(kind='text', text='\u0412 \ua7cb \U00010d50')])
            assert [(document['seq'], document['text']) for document in documents] == [(2, '\u1c80 \u0264 \U00010d70')]
            assert context.get('sessions').get('s') is None
        finally:
            await query.close()
    finally:
        await context.fiber.dispose()
    context, _, _ = await mount(backend)
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='never'))
    try:
        documents = await query.filterEvents('s', [dict(kind='text', text='\u0412 \ua7cb \U00010d50')])
        assert [(document['seq'], document['text']) for document in documents] == [(2, '\u1c80 \u0264 \U00010d70')]
        assert context.get('sessions').get('s') is None
    finally:
        await query.close()
        await context.fiber.dispose()
