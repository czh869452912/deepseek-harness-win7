import asyncio
import json

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.credentials.authorization_current import CurrentAuthorizationService
from dsh.credentials.local_current import CurrentCredentialsLocalPlugin as CredentialsLocalPlugin
from scripts import rc022_authorization_probe as corpus


@pytest.mark.asyncio
async def test_authorization_source_corpus(tmp_path):
    rows = await corpus.observe()
    (tmp_path/'authorization-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 26
    modes = {row['mode']: row for row in rows}
    assert modes['late-commit']['records'] == {}
    assert modes['withdrawn-orphan']['result'] == dict(value=dict(status='cancelled'))
    for mode in ('commit-cancel', 'external-commit-cancel', 'unload-commit'):
        assert modes[mode]['result'] == dict(value=dict(status='authorized'))
        assert 'admitted-aborted:false' in modes[mode]['calls']
    assert modes['settled-listener-failure']['result'] == dict(value=dict(status='authorized'))
    assert 'later-listener' in modes['settled-listener-failure']['calls']
    assert all(row['listeners'] == 0 and row['after'] == [] for row in rows)
    assert all(not event['inFlight'] for row in rows for event in row['settled'])


@pytest.mark.asyncio
async def test_authorization_commits_with_canonical_local_credential_provider(tmp_path):
    ctx = Context(); path = tmp_path/'credentials.yml'
    try:
        await ctx.plugin(CredentialsLocalPlugin, dict(path=str(path), watch=False))
        await ctx.plugin(CurrentAuthorizationService)
        async def run(session):
            await session.commit(dict(kind='grant', payload=dict(token='test-token', version=1)))
        ctx.authorization.registerFlow(dict(key='provider/login', label='Login', methods=[dict(id='browser', label='Browser')], run=run))
        result = await ctx.authorization.begin(dict(key='provider/login', interaction=dict(notify=lambda *_: None, prompt=lambda *_: 'typed')))
        assert result == dict(status='authorized')
        assert ctx.credentials.readRecord('provider/login')['payload']['token'] == 'test-token'
        assert 'test-token' in path.read_text(encoding='utf-8')
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_begin_claims_slot_before_return_and_late_commit_cannot_enter_reused_slot(tmp_path):
    ctx = Context(); sessions = []; gate = asyncio.get_running_loop().create_future()
    try:
        await ctx.plugin(CredentialsLocalPlugin, dict(path=str(tmp_path/'credentials.yml'), watch=False))
        await ctx.plugin(CurrentAuthorizationService)
        async def run(session):
            sessions.append(session); await gate
        ctx.authorization.registerFlow(dict(key='provider/login', label='Login', methods=[dict(id='browser', label='Browser')], run=run))
        request = dict(key='provider/login', interaction=dict(notify=lambda *_: None, prompt=lambda *_: 'typed'))
        first = ctx.authorization.begin(request)
        assert ctx.authorization.describe('provider/login')['inFlight']
        ctx.authorization.cancel('provider/login'); assert await first == dict(status='cancelled')
        second = ctx.authorization.begin(request)
        with pytest.raises(Exception):
            await sessions[0].commit(dict(kind='grant', payload='late'))
        assert ctx.credentials.readRecord('provider/login') is None
        ctx.authorization.cancel('provider/login'); assert await second == dict(status='cancelled')
        gate.set_result(None)
        await asyncio.sleep(0); await asyncio.sleep(0)
    finally:
        if not gate.done(): gate.set_result(None)
        await ctx.fiber.dispose()
