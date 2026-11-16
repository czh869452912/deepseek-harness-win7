"""Actual account credential, detail and identity consumers with controlled transport."""
import copy
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return ['stored', 'signed-out', 'foreign', 'invalid-record', 'invalid-payload', 'invalid-version',
            'invalid-token', 'invalid-issuer', 'mock-token', 'private', 'expired-http', 'expired-code',
            'profile-failed', 'balance-failed', 'notification-failed', 'reject-old', 'reject-current', 'sign-out']


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.awaiting import await_callback_result
    from dsh.core.abort import AbortController
    from dsh.credentials.authorization_current import CurrentAuthorizationService
    from dsh.credentials.account_state import AccountState, KEY, DEVICE
    from dsh.credentials import account_protocol as protocol
    rows = []; original_request = protocol.request; original_diagnostic = protocol._diagnostic
    try:
        for mode in cases():
            ctx = Context(); records = {}; hits = []; diagnostics = []; events = []
            issuer = 'https://private.example' if mode == 'private' else 'https://platform.deepseek.com'
            record = dict(kind='grant', payload=dict(version=1, token='dsh_mock_fixture' if mode == 'mock-token' else 'fixture-token', issuer=issuer))
            if mode == 'foreign': record['payload']['issuer'] = 'https://other.example'
            elif mode == 'invalid-record': record = dict(kind='api-key', apiKey='secret')
            elif mode == 'invalid-payload': record['payload'] = None
            elif mode == 'invalid-version': record['payload']['version'] = True
            elif mode == 'invalid-token': record['payload']['token'] = ''
            elif mode == 'invalid-issuer': record['payload']['issuer'] = 'bad-url'
            if mode != 'signed-out': records[KEY] = record
            records[DEVICE] = dict(kind='grant', payload=dict(id='12345678-1234-4234-8234-123456789abc'))
            async def read(key): return copy.deepcopy(records.get(key))
            async def delete(key):
                if key in records:
                    del records[key]; ctx.emit('credentials/record-updated', key)
            async def modify(key, mutate):
                value = await await_callback_result(mutate(records.get(key)))
                if value is not None:
                    records[key] = value; ctx.emit('credentials/record-updated', key)
                return records.get(key)
            async def describe(key): return dict(configured=key in records)
            ctx.set_service('credentials', SimpleNamespace(readRecord=read, deleteRecord=delete, modifyRecord=modify, describeRecord=describe))
            await ctx.plugin(CurrentAuthorizationService)
            for event in ('deepseek-account/session-expired', 'deepseek-account/signed-out'):
                ctx.on(event, lambda event=event: events.append(event))
            stage = 'profile'; current_user = 'user-1'
            @asynccontextmanager
            async def request(url, method, headers, body, signal):
                hits.append(dict(url=url, method=method, headers={key.lower(): value for key, value in headers.items()}, body=body))
                path = url.split('.com')[-1] if '.com' in url else url.split('.example')[-1]
                payload = dict(id=current_user, email='masked', id_profile=dict(name='Name', picture='url'))
                if path.endswith('/get_user_summary'): payload = dict(normal_wallets=[dict(currency='CNY', balance='0E-16')], bonus_wallets=[])
                elif path.endswith('/notifications/list'): payload = dict(next_poll_after=600, notifications=[])
                elif path.endswith('/logout'): payload = None
                status = 401 if mode == 'expired-http' and stage == 'profile' else 200
                envelope = dict(code=0, data=dict(biz_code=0, biz_data=payload))
                if mode == 'expired-code' and stage == 'profile': envelope = {'code': 40003}
                if (mode == 'profile-failed' and stage == 'refresh') or (mode == 'balance-failed' and path.endswith('/get_user_summary')) or (mode == 'notification-failed' and path.endswith('/notifications/list')):
                    status = 503
                async def chunks(): yield json.dumps(envelope, ensure_ascii=True).encode('utf-8')
                yield dict(status=status, hasBody=True), chunks()
            protocol.request = request
            protocol._diagnostic = lambda label, value: diagnostics.append(dict(label=label, **value))
            account = None
            try:
                config = dict(requestHeaders={'Cookie': 'a=1; keep=base', 'x-deployment': 'base'},
                              accountRequestHeaders={'cookie': 'a=2; extra=override', 'x-account': 'account'}, embeddedPageDist='desktop-dist')
                if mode == 'private': config.update(platformOrigin=issuer, inferenceOrigin='https://inference.example')
                account = AccountState(ctx, config); await account.initialize()
                initial = await account.getState()
                destinations = ['https://api.deepseek.com/anthropic/v1/messages', 'https://inference.example/v1/files',
                                'https://api.deepseek.com:443/files?x=1', 'https://user@api.deepseek.com/files', 'https://other.example']
                tokens = [await account.resolveToken(url) for url in destinations]
                client = dict(version='fixture/1', locale='zh_TW', timezoneOffsetSeconds=28800)
                changes = []; account.listeners.append(changes.append)
                profile = await account.getProfile(client); session = await account.getPlatformSession()
                stage = 'refresh'; refresh = await account.getProfile(client)
                current_user = 'user-2'; stage = 'identity'; identity = await account.getProfile(client)
                balance = await account.getBalance(client)
                try: batch = dict(value=await account.getNotifications(client))
                except Exception as error: batch = dict(error=dict(message=str(error), code=getattr(error, 'code', None)))
                device = await account.getDeviceIdentity()
                if mode in ('reject-old', 'reject-current'): await account.rejectToken('old-token' if mode == 'reject-old' else 'fixture-token')
                if mode == 'sign-out': await account.signOut(client)
                result = dict(initial=initial, tokens=tokens, profile=profile, session=session, refresh=refresh, identity=identity,
                              balance=balance, batch=batch, device=device, final=await account.getState(), changes=changes,
                              running=account.hasRunningAccountTasks())
            except Exception as error:
                result = dict(error=dict(message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None)))
            finally:
                await ctx.fiber.dispose()
            rows.append(dict(mode=mode, result=result, records=records, hits=hits, diagnostics=diagnostics, events=events))
        return rows
    finally:
        protocol.request = original_request; protocol._diagnostic = original_diagnostic


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_account_state.mts', 'Actual account state, grant initialization/resolution, query lifetimes, identity cache and removal.',
        [Path(__file__).resolve(), ROOT/'dsh/credentials/account_state.py', ROOT/'dsh/credentials/account_lifetime.py'], prepare=prepare)
