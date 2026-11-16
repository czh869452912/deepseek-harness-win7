import asyncio
import json
import threading

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.credentials.authorization_current import CurrentAuthorizationService
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.credentials.deepseek_account_current import CurrentDeepSeekAccount, _completion
from dsh.typert.remote import remote_methods
from scripts import rc022_account_login_probe as corpus


@pytest.mark.asyncio
async def test_actual_browser_pkce_callbacks_commit_and_failure_documents(tmp_path):
    before = {thread.ident for thread in threading.enumerate()}
    rows = await corpus.observe()
    (tmp_path/'account-login-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
    assert len(rows) == 17
    modes = {row['mode']: row for row in rows}
    assert modes['success']['result']['profile']['value']['id'] == 'user-id'
    assert modes['invalid-user']['result']['profile']['value']['id'] == 'fallback-user'
    assert modes['invalid-callbacks']['result']['invalid'] == [400]*5
    assert modes['duplicate-callback']['result']['invalid'] == [410]
    assert modes['cancel-exchanging']['result']['final']['attempt']['phase'] == 'cancelled'
    assert modes['expire-waiting']['result']['final']['attempt']['phase'] == 'expired'
    assert modes['commit-cancel']['result']['final']['attempt']['phase'] == 'succeeded'
    assert modes['init-timeout']['result']['final']['attempt']['errorCode'] == 'no-response'
    assert modes['exchange-failure-zh']['result']['callback']['status'] == 200
    assert '登录失败' in modes['exchange-failure-zh']['result']['callback']['body']
    assert modes['exchange-failure-desktop']['result']['callback']['status'] == 204
    assert all(row['result']['routeGone'] and not row['result']['flowInFlight'] for row in rows)
    assert 'must-discard' not in json.dumps(rows)
    logs = json.dumps([row['diagnostics'] for row in rows])
    for secret in ('private-secret', 'fixture-token', 'fixture-code', 'invalid token'):
        assert secret not in logs
    for _ in range(100):
        active = [thread for thread in threading.enumerate() if thread.ident not in before and thread.name in
                  ('dsh-model-reader', 'dsh-http-cancellation', 'account-login-probe')]
        if not active: break
        await asyncio.sleep(.002)
    assert not active


@pytest.mark.asyncio
async def test_account_remote_namespace_excludes_host_credentials_and_no_webserver_fails_cleanly(tmp_path):
    ctx = Context()
    try:
        await ctx.plugin(CredentialsLocalPlugin, dict(path=str(tmp_path/'credentials.yml'), watch=False))
        await ctx.plugin(CurrentAuthorizationService)
        await ctx.plugin(CurrentDeepSeekAccount, dict(desktopPlatform=None, logoutMaxRetries=1.0))
        account = ctx.deepseekAccount
        assert account.typertRemote['namespace'] == 'account'
        methods = remote_methods(account)
        assert sorted(row.get('exportName', row['method']) for row in methods) == sorted([
            'cancelSignIn', 'getBalance', 'getNotificationContent', 'getNotifications', 'getProfile', 'getState',
            'hasRunningAccountTasks', 'reportNotificationEvent', 'signOut', 'startSignIn', 'watch', 'watchExpiry'])
        assert sorted(row.get('exportName', row['method']) for row in methods if row.get('mode') == 'stream') == ['watch', 'watchExpiry']
        await account.startSignIn(dict(version='fixture', locale='en', timezoneOffsetSeconds=0), 'http://localhost:80', 'web')
        await account.attempt.done
        assert (await account.getState())['attempt']['phase'] == 'failed'
        assert not ctx.authorization.describe('deepseek-account-platform/default')['inFlight']
    finally:
        await ctx.fiber.dispose()


def test_completion_url_search_params_replace_duplicates_and_preserve_empty_fragment():
    assert _completion('https://platform.example/dsh/authorized?x=a%2Fb&login_source=old&login_source=duplicate&v=~#', 'web') == (
        'https://platform.example/dsh/authorized?x=a%2Fb&login_source=web&v=%7E#')
