import asyncio
import json
import threading

import pytest

from dsh.core.abort import AbortController
from dsh.credentials import account_logout as logout, account_notifications as notifications
from scripts import rc022_account_notification_probe as corpus
from scripts import rc022_account_logout_probe as logout_corpus


@pytest.mark.asyncio
async def test_notification_and_login_schema_source_corpus(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'account-notification-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == len(corpus.cases())
    assert 'discard-secret' not in json.dumps(rows)
    assert any(row['result'].get('value', {}).get('notifications') for case, row in zip(corpus.cases(), rows) if case['kind'] == 'list')


@pytest.mark.asyncio
async def test_actual_logout_http_preserves_captured_token_and_releases_workers(tmp_path):
    before = {thread.ident for thread in threading.enumerate()}
    rows = await logout_corpus.observe()
    (tmp_path/'account-logout-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 17
    assert all(row['listeners'] == 0 for row in rows)
    assert len(rows[11]['hits']) == 6
    assert all(hit['token'] == 'captured-old-token' for row in rows for hit in row['hits'])
    for _ in range(100):
        active = [thread for thread in threading.enumerate() if thread.ident not in before and thread.name in
                  ('dsh-model-reader', 'dsh-http-cancellation', 'account-logout-probe')]
        if not active:
            break
        await asyncio.sleep(.002)
    assert not active


@pytest.mark.asyncio
async def test_logout_exponential_delays_stop_on_success_and_cancelled_delay(monkeypatch):
    calls = []; delays = []; controller = AbortController()
    policy = dict(maxRetries=5, delayMs=1000, requestTimeoutMs=30000)
    async def fail(origin, token, signal, headers):
        calls.append((token, signal, headers))
        raise RuntimeError('offline')
    async def delay(milliseconds, signal):
        delays.append(milliseconds)
    monkeypatch.setattr(logout, 'logoutAccount', fail); monkeypatch.setattr(logout, '_delay', delay)
    await logout.revokeAccount('https://platform.example', 'old', policy, controller.signal, {'x': 'y'})
    assert delays == [1000, 2000, 4000, 8000, 16000]
    assert len(calls) == 6 and all(call[0] == 'old' for call in calls)
    assert controller.signal._listeners == []
    assert all(not call[1].aborted for call in calls)
    async def cancelled_delay(milliseconds, signal):
        controller.abort(); raise RuntimeError('cancelled')
    calls.clear(); monkeypatch.setattr(logout, '_delay', cancelled_delay)
    await logout.revokeAccount('https://platform.example', 'old', policy, controller.signal, {})
    assert len(calls) == 1 and controller.signal._listeners == []


def test_notification_projection_detaches_json_and_discards_unknown_action_fields():
    value = corpus.wire()
    value.update(data={'nested': ['old']}, actions=[dict(label='Close', style='primary', target=dict(type='dismiss', ignored='secret'), ignored='secret')])
    result, issues = notifications._notification(value)
    value['data']['nested'][0] = 'changed'
    assert not issues and result['data'] == {'nested': ['old']}
    assert result['actions'] == [dict(label='Close', style='primary', target=dict(type='dismiss'))]
