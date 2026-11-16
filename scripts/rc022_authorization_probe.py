"""Actual authorization ownership, commit admission and terminal settlement."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return ['commit', 'direct-write', 'missing-write', 'stale-record', 'deleted-record', 'flow-failure',
            'decline', 'wrapped-decline', 'prompt-failure', 'notice-failure', 'pre-abort', 'pre-abort-no-flow',
            'pre-abort-bad-method', 'no-flow', 'bad-method', 'empty-method', 'duplicate', 'withdrawn-orphan',
            'commit-cancel', 'external-commit-cancel', 'unload-commit', 'unload-running', 'late-commit',
            'settled-listener-failure', 'settled-reentry', 'commit-storage-failure']


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.awaiting import await_callback_result
    from dsh.core.abort import AbortController
    from dsh.credentials.authorization_current import CurrentAuthorizationService
    from dsh.credentials.authorization import AuthorizationDeclinedError
    rows = []; key = 'provider/login'
    for mode in cases():
        ctx = Context(); controller = AbortController(); records = {}; calls = []; settled = []; notices = []; prompts = []
        gate = asyncio.get_running_loop().create_future(); entered = asyncio.get_running_loop().create_future(); session_box = []
        if mode == 'stale-record': records[key] = dict(kind='grant', payload='old')
        async def modify(name, mutate):
            next_record = await await_callback_result(mutate(records.get(name)))
            if mode in ('commit-cancel', 'external-commit-cancel', 'unload-commit'):
                if not entered.done(): entered.set_result(None)
                await gate
            if mode == 'commit-storage-failure': raise RuntimeError('storage unavailable')
            records[name] = next_record; ctx.emit('credentials/record-updated', name); calls.append('write')
            return next_record
        async def describe(name): return dict(configured=name in records)
        ctx.set_service('credentials', SimpleNamespace(modifyRecord=modify, describeRecord=describe))
        await ctx.plugin(CurrentAuthorizationService); auth = ctx.authorization
        ctx.on('authorization/settled', lambda key, status: settled.append(dict(key=key, status=status, inFlight=auth.describe(key)['inFlight'] if auth.describe(key) else None)))
        if mode == 'settled-listener-failure':
            def bad(*_): raise RuntimeError('listener failure')
            async def bad_async(*_): raise RuntimeError('async listener failure')
            ctx.on('authorization/settled', bad); ctx.on('authorization/settled', bad_async)
            ctx.on('authorization/settled', lambda *_: calls.append('later-listener'))
        def notify(notice):
            notices.append(notice)
            if mode == 'notice-failure': raise RuntimeError('notice failed')
        async def prompt(value):
            prompts.append(value)
            if mode in ('decline', 'wrapped-decline'): raise AuthorizationDeclinedError()
            if mode == 'prompt-failure': raise RuntimeError('prompt failed')
            return 'typed'
        async def run(session):
            session_box.append(session); calls.append('run')
            if mode in ('withdrawn-orphan', 'unload-running', 'late-commit'):
                entered.set_result(None); await gate
                if mode == 'late-commit': await session.commit(dict(kind='grant', payload='late'))
                else: raise RuntimeError('late failure')
                return
            if mode in ('missing-write', 'stale-record'): return
            if mode == 'flow-failure': raise RuntimeError('flow failed')
            if mode in ('decline', 'wrapped-decline', 'prompt-failure'):
                try: await session.prompt(dict(message='Question'))
                except Exception:
                    if mode == 'wrapped-decline': raise RuntimeError('wrapped decline')
                    raise
            session.notify(dict(message='Notice'))
            if mode == 'direct-write': await modify(key, lambda *_: dict(kind='grant', payload='value'))
            else: await session.commit(dict(kind='grant', payload='value'))
            if mode == 'deleted-record': records.pop(key); ctx.emit('credentials/record-updated', key)
        dispose = auth.registerFlow(dict(key=key, label='Provider', methods=[dict(id='browser', label='Browser')], run=run))
        entry = auth.list(); duplicate = None
        if mode == 'duplicate':
            try: auth.registerFlow(dict(key=key, label='Other', methods=[], run=run))
            except Exception as error: duplicate = getattr(error, 'code', None)
        if mode.startswith('pre-abort'): controller.abort(RuntimeError('caller withdrew'))
        request = dict(key='other/login' if mode in ('no-flow', 'pre-abort-no-flow') else key,
                       signal=controller.signal, interaction=dict(notify=notify, prompt=prompt))
        if mode in ('bad-method', 'pre-abort-bad-method', 'empty-method'): request['method'] = '' if mode == 'empty-method' else 'other'
        if mode == 'settled-reentry':
            def reentry(*_):
                if 'reentered' not in calls:
                    calls.append('reentered')
                    controller.abort()
            ctx.on('authorization/settled', reentry)
        active = auth.begin(request); busy = None
        try:
            if mode in ('withdrawn-orphan', 'unload-running', 'late-commit', 'commit-cancel', 'external-commit-cancel', 'unload-commit'):
                await entered
                try: await auth.begin(dict(request))
                except Exception as error: busy = getattr(error, 'code', None)
                if mode.startswith('unload'): await await_callback_result(dispose())
                elif mode == 'external-commit-cancel': controller.abort()
                else: auth.cancel(key)
                if 'commit' in mode and mode != 'late-commit':
                    calls.append('admitted-aborted:'+str(session_box[0].signal.aborted).lower())
                    gate.set_result(None)
                else:
                    outcome = await active
                    gate.set_result(None)
                    await asyncio.sleep(0); await asyncio.sleep(0); await asyncio.sleep(0)
                    result = dict(value=outcome)
            if mode not in ('withdrawn-orphan', 'unload-running', 'late-commit'):
                result = dict(value=await active)
        except Exception as error:
            result = dict(error=dict(message=getattr(error, 'message', str(error)), code=getattr(error, 'code', None)))
        await asyncio.sleep(0); await asyncio.sleep(0)
        await await_callback_result(dispose())
        rows.append(dict(mode=mode, entry=entry, result=result, duplicate=duplicate, busy=busy, calls=calls,
                         notices=notices, prompts=prompts, settled=settled, records=records,
                         listeners=len(controller.signal._listeners), after=auth.list()))
        await ctx.fiber.dispose()
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_authorization.mts', 'Actual async authorization, flow ownership, commit cancellation boundary and contained settlement.',
        [Path(__file__).resolve(), ROOT/'dsh/credentials/authorization_current.py'], prepare=prepare)
