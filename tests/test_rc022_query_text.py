from dsh.session.session_query import extract_session_event_text as legacy_extract
from dsh.session.text_current import extract_session_event_text
import pytest


def test_current_semantics_ignore_nested_legacy_results_and_unknown_blocks():
    nested = dict(type='tool-result', toolCallId='nested', content=[dict(type='text', text='private nested')])
    content = [dict(type='text', text=' visible '), nested,
               dict(type='reasoning', text='private reasoning'),
               dict(type='tool-call', name=' tool ', arguments=' {} ')]
    user = dict(type='user/message', data=dict(content=content))
    assert extract_session_event_text(user) == 'visible\ntool\n{}'
    assert legacy_extract(user) == 'visible\nprivate nested\ntool\n{}'
    assert extract_session_event_text(dict(type='assistant/message', data=dict(message=dict(content=content)))) == 'visible\ntool\n{}'
    assert extract_session_event_text(dict(type='tool/result', data=dict(
        message=dict(content=content), error=dict(name=' Failure ', code=' ERROR ')))) == 'visible\ntool\n{}\nFailure\nERROR'


def test_current_documents_use_current_semantic_extractor():
    from dsh.session.query_current import documents
    event = dict(type='user/message', seq=0, time=1, surfaceOp='append', data=dict(
        id='message-0', role='user', source=dict(kind='user'), content=[
            dict(type='text', text='visible'),
            dict(type='tool-result', toolCallId='old', content=[dict(type='text', text='private')])]))
    assert [row['text'] for row in documents('session', [event])] == ['visible']


@pytest.mark.asyncio
async def test_actual_current_query_filter_uses_pinned_node24_case_folding():
    from dsh.cordis import Context
    from dsh.core.runtime_v4 import SessionV4Plugin
    from dsh.session.query_current import CurrentSessionQueryService
    from dsh.session.session_query import compile_session_text_filter as legacy_compile
    from dsh.session.text_current import compile_session_text_filter
    # This pair was introduced in Unicode 17 and does not fold in Node 24.9.0.
    assert legacy_compile('\ua7ce').search('\ua7cf')
    assert not compile_session_text_filter('\ua7ce').search('\ua7cf')
    ctx = Context()
    await ctx.plugin(SessionV4Plugin)
    try:
        session = ctx.sessions.create('fold')
        session.append('user/message', dict(id='message-0', role='user', source=dict(kind='user'),
            content=[dict(type='text', text='\ua7cf')]), surface_op='append')
        query = CurrentSessionQueryService(ctx)
        assert await query.filterEvents('fold', [dict(kind='text', text='\ua7ce')]) == []
        assert len(await query.filterEvents('fold', [dict(kind='text', text='\ua7cf')])) == 1
    finally:
        await ctx.fiber.dispose()


def test_current_case_folding_refuses_damaged_data(tmp_path):
    from dsh.session.text_current import verify_case_folding
    path = tmp_path / 'CaseFolding.txt'
    path.write_text('foreign Unicode data', encoding='utf-8')
    with pytest.raises(RuntimeError, match='case-folding data differs'):
        verify_case_folding(path)
