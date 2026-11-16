import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.credentials.account_state import AccountState, KEY
from dsh.credentials.authorization_current import CurrentAuthorizationService
from dsh.credentials.local_current import CurrentCredentialsLocalPlugin as CredentialsLocalPlugin
from dsh.credentials import account_state as module
from dsh.llm.llm_service import LlmError
from scripts import rc022_account_state_probe as corpus


CLIENT = dict(version='test', locale='en', timezoneOffsetSeconds=0)


async def fixture(tmp_path):
    ctx = Context()
    await ctx.plugin(CredentialsLocalPlugin, dict(path=str(tmp_path/'credentials.yml'), watch=False))
    await ctx.plugin(CurrentAuthorizationService)
    await ctx.credentials.modifyRecord(KEY, lambda *_: dict(kind='grant', payload=dict(version=1, token='old', issuer='https://platform.deepseek.com')))
    await ctx.plugin(AccountState, dict(desktopPlatform=None))
    return ctx, ctx.deepseekAccount


async def replace(ctx, token):
    await ctx.credentials.modifyRecord(KEY, lambda *_: dict(kind='grant', payload=dict(version=1, token=token, issuer='https://platform.deepseek.com')))


@pytest.mark.asyncio
async def test_account_state_source_corpus(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'account-state-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 18
    by_mode = {row['mode']: row for row in rows}
    assert by_mode['profile-failed']['result']['refresh'] == by_mode['profile-failed']['result']['profile']
    assert by_mode['balance-failed']['result']['balance'] == dict(status='failed')
    assert by_mode['mock-token']['result']['tokens'] == [None]*5
    assert by_mode['reject-old']['result']['final']['status'] == 'credential-stored'
    assert by_mode['reject-current']['result']['final']['status'] == 'signed-out'
    assert by_mode['sign-out']['events'] == ['deepseek-account/signed-out']
    assert by_mode['foreign']['result']['initial']['status'] == 'signed-out'


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['profile', 'balance', 'notifications'])
async def test_stale_query_is_discarded_after_credential_generation_changes(tmp_path, monkeypatch, field):
    ctx, account = await fixture(tmp_path); entered = asyncio.Event(); gate = asyncio.get_running_loop().create_future(); captured = []
    async def held(*args):
        captured.append(args[-2]); entered.set(); await gate
        return dict(status='ready', value=dict(id='old-user')) if field != 'notifications' else dict(nextPollAfterSeconds=1, notifications=[])
    monkeypatch.setattr(module, 'readNotifications' if field == 'notifications' else 'readAccountDetail', held)
    try:
        task = asyncio.create_task(getattr(account, dict(profile='getProfile', balance='getBalance', notifications='getNotifications')[field])(CLIENT))
        await entered.wait(); await replace(ctx, 'new'); assert captured[0].aborted
        gate.set_result(None); assert await task is None
        assert (await account.getPlatformSession())['token'] == 'new'
        assert (await account.getPlatformSession())['userId'] is None
        await account.rejectToken('old')
        assert (await account.getState())['status'] == 'credential-stored'
    finally:
        if not gate.done(): gate.set_result(None)
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_identity_opt_in_credential_priority_and_expiry_stream_cleanup(tmp_path):
    ctx, account = await fixture(tmp_path); plain_abort = AbortController(); identity_abort = AbortController(); expiry_abort = AbortController()
    plain = account.watch(plain_abort.signal); identity = account.watch(identity_abort.signal, True); expiry = account.watchExpiry(expiry_abort.signal)
    try:
        assert (await plain.__anext__())['type'] == 'snapshot'
        assert (await identity.__anext__())['type'] == 'snapshot'
        plain_next = asyncio.create_task(plain.__anext__()); identity_next = asyncio.create_task(identity.__anext__())
        await asyncio.sleep(0)
        account.cacheProfile('old', dict(status='ready', value=dict(id='id')))
        assert (await identity_next)['type'] == 'snapshot'
        assert not plain_next.done()
        # Priority is defined within a single notification burst. A durable
        # credential edit now crosses asynchronous lock/write boundaries.
        account.changed('snapshot'); account.changed('credentials-changed'); account.changed('snapshot')
        assert (await plain_next)['type'] == 'credentials-changed'
        expired = asyncio.create_task(expiry.__anext__()); await asyncio.sleep(0)
        ctx.emit('deepseek-account/session-expired'); assert await expired == 'session-expired'
        pending = asyncio.create_task(plain.__anext__()); await asyncio.sleep(0); plain_abort.abort()
        with pytest.raises(StopAsyncIteration): await pending
        assert plain_abort.signal._listeners == []
    finally:
        await plain.aclose(); await identity.aclose(); await expiry.aclose()
        assert account.listeners == []
        assert identity_abort.signal._listeners == [] and expiry_abort.signal._listeners == []
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_late_agents_binding_uses_latest_request_context_and_unloads(tmp_path):
    ctx, account = await fixture(tmp_path); calls = []; route = ['deepseek-account']; signins = []
    account_agent = SimpleNamespace(status='running', session=SimpleNamespace(requestContext=lambda: dict(provider=route[0])), cancel=lambda *args: calls.append(args))
    other = SimpleNamespace(status='idle', session=SimpleNamespace(requestContext=lambda: dict(provider='deepseek-account')), cancel=lambda *args: calls.append(('idle', args)))
    try:
        ctx.set_service('agents', SimpleNamespace(list=lambda: [account_agent, other]))
        for _ in range(20):
            await asyncio.sleep(0)
        ctx.on('deepseek-account/model-sign-in-required', lambda: signins.append(True))
        assert account.hasRunningAccountTasks()
        ctx.emit('agent/error', dict(error=LlmError('sign in', 'ACCOUNT_SIGN_IN_REQUIRED')))
        assert signins == [True]
        ctx.emit('deepseek-account/signed-out')
        assert calls == [(dict(kind='hook', reason='deepseek-account/signed-out'), dict(keepInbox=True))]
        route[0] = 'deepseek-official'
        assert not account.hasRunningAccountTasks()
        ctx.emit('deepseek-account/signed-out'); assert len(calls) == 1
    finally:
        await ctx.fiber.dispose()
