import pytest
from dsh.cordis.context import Context
from dsh.core.session import Session, SessionStore
from dsh.session.title import (
    fallback_session_title,
    fold_session_title,
    normalize_session_title,
    truncate_title_utf8,
    SessionTitleService,
    SessionTitlePlugin,
)


def test_session_title_normalization():
    assert normalize_session_title('\u001B]0;stolen\u0007  Hello\t brave\nnew world  ', 80) == 'Hello brave new world'
    assert fallback_session_title('one two three four', 3, 80) == 'one two three'
    assert fallback_session_title('你好世界', 5, 7) == '你好'
    assert len(fallback_session_title('😀😀', 5, 5).encode('utf-8')) == 4


def test_rejects_non_positive_limits():
    with pytest.raises(ValueError, match='maxBytes must be a positive integer'):
        truncate_title_utf8('title', 0)
    with pytest.raises(ValueError, match='maxWords must be a positive integer'):
        fallback_session_title('title', 0, 10)


def test_session_title_service_fallback_and_fold():
    ctx = Context()
    store = SessionStore(ctx)
    ctx.set_service('sessions', store)
    title_svc = SessionTitleService(ctx, {'fallbackMaxWords': 5, 'fallbackMaxBytes': 40, 'maxTitleBytes': 80})
    ctx.set_service('sessionTitle', title_svc)

    session = store.create('sess-title-1')
    session.append('turn/start', {'turn': 1})
    session.append_user_message('  Build\nlog-backed session titles please  ')

    snap = title_svc.get(session)
    assert snap is not None
    assert snap['title'] == 'Build log-backed session titles please'
    assert snap["source"]["kind"] == 'fallback'

    # Test rename
    title_svc.rename(session, 'My Renamed Session')
    snap2 = title_svc.get(session)
    assert snap2['title'] == 'My Renamed Session'
    assert snap2["source"]["kind"] == 'user'

    # Test empty rename rejection
    with pytest.raises(ValueError, match='visible characters'):
        title_svc.rename(session, '   \t \n  ')
