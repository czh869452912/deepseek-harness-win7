import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_acp_session_controls import bridge_fixture, dispose_context
from dsh.core.session import SessionHeader


async def observe():
    cwd = str(ROOT)
    modes = ['empty', 'pagination', 'filter', 'cursors', 'resume-refusals', 'reservation', 'shared-close', 'close-failure']
    observations = []
    for mode in modes:
        ctx, bridge, persistence, factory = bridge_fixture(2 if mode == 'pagination' else 100)
        try:
            if mode == 'empty':
                created = await bridge.new_session(ctx, {'cwd': cwd})
                materialized = created['sessionId'] in persistence.headers
                hidden = await bridge.list_sessions(ctx, {})
                closed = await bridge.close_session(ctx, created)
                listed = await bridge.list_sessions(ctx, {})
                await bridge.resume_session(ctx, dict(created, cwd=cwd))
                observations.append({'mode': mode, 'materialized': materialized, 'hidden': hidden, 'closed': closed,
                    'listedIdentity': len(listed['sessions']) == 1 and listed['sessions'][0]['sessionId'] == created['sessionId'],
                    'listedCwd': listed['sessions'][0]['cwd'], 'hiddenAfterResume': await bridge.list_sessions(ctx, {})})
            if mode == 'pagination':
                persistence.headers = {name: SessionHeader(name, created_at=12 if name == 'new' else 9 if name == 'old' else 10, cwd=cwd)
                                       for name in ['😀', 'old', 'β', 'Z', 'a', 'new']}
                pages, cursor = [], None
                while True:
                    page = await bridge.list_sessions(ctx, {'cursor': cursor})
                    pages.append(page)
                    cursor = page.get('nextCursor')
                    if cursor is None:
                        break
                observations.append({'mode': mode, 'pages': pages})
            if mode == 'filter':
                created = await bridge.new_session(ctx, {'cwd': cwd})
                directory = str(ROOT / 'missing-filter')
                rows = [SessionHeader(created['sessionId'], created_at=100, cwd=directory),
                    SessionHeader('subagent', created_at=99, cwd=directory, origin='subagent'),
                    SessionHeader('fork', created_at=98, cwd=directory, parent_session='parent'),
                    SessionHeader('no-cwd', created_at=97), SessionHeader('relative', created_at=96, cwd='relative'),
                    SessionHeader('foreign', created_at=95, cwd=directory), SessionHeader('other', created_at=94, cwd=str(ROOT / 'other')),
                    SessionHeader('valid-b', created_at=3, cwd=directory), SessionHeader('valid-a', created_at=3, cwd=directory)]
                persistence.headers = {header.id: header for header in rows}
                factory.live['foreign'] = object()
                observations.append({'mode': mode, 'result': await bridge.list_sessions(ctx, {'cwd': str(ROOT / 'missing-filter' / 'nested' / '..')})})
            if mode == 'cursors':
                values = ['', '*', 'A', 'bnVsbA', 'W10', 'Wy0xLCJpZCJd', 'WzEsIiJd', 'W3RydWUsImlkIl0', 'WzEsImlkIl0=', 'WyAxLCAiaWQiIF0']
                rejected = []
                for cursor in values:
                    try:
                        await bridge.list_sessions(ctx, {'cursor': cursor})
                        rejected.append(False)
                    except ValueError as error:
                        rejected.append('cursor is invalid' in str(error))
                assert all(rejected)
                observations.append({'mode': mode, 'rejected': rejected})
            if mode == 'resume-refusals':
                created = await bridge.new_session(ctx, {'cwd': cwd})
                rows = [SessionHeader('subagent', created_at=9, cwd=cwd, origin='subagent'),
                    SessionHeader('fork', created_at=8, cwd=cwd, parent_session='parent'), SessionHeader('no-cwd', created_at=7),
                    SessionHeader('wrong', created_at=6, cwd=str(ROOT / 'other'))]
                persistence.headers = {header.id: header for header in rows}
                cases = [('unknown', 'not resumable'), ('subagent', 'not resumable'), ('fork', 'not resumable'),
                         ('no-cwd', 'cwd does not match'), ('wrong', 'cwd does not match'), (created['sessionId'], 'already active')]
                rejected = []
                for session_id, detail in cases:
                    try:
                        await bridge.resume_session(ctx, {'sessionId': session_id, 'cwd': cwd})
                        rejected.append(False)
                    except ValueError as error:
                        rejected.append(detail in str(error))
                assert all(rejected)
                observations.append({'mode': mode, 'rejected': rejected, 'factoryCalls': len(factory.resumed)})
            if mode == 'reservation':
                entered, release = asyncio.Event(), asyncio.Event()
                first = True
                async def listed():
                    nonlocal first
                    if first:
                        first = False
                        entered.set()
                        await release.wait()
                        return []
                    return [SessionHeader('saved', cwd=cwd)]
                calls = 0
                async def resume(**kwargs):
                    nonlocal calls
                    calls += 1
                    raise RuntimeError('fixture factory failure')
                persistence.list, factory.resume = listed, resume
                pending = asyncio.create_task(bridge.resume_session(ctx, {'sessionId': 'saved', 'cwd': cwd}))
                await entered.wait()
                hidden = await bridge.list_sessions(ctx, {})
                try:
                    await bridge.resume_session(ctx, {'sessionId': 'saved', 'cwd': cwd})
                    duplicate = False
                except ValueError as error:
                    duplicate = 'already active' in str(error)
                release.set()
                try:
                    await pending
                    first_rejected = False
                except ValueError as error:
                    first_rejected = 'not resumable' in str(error)
                try:
                    await bridge.resume_session(ctx, {'sessionId': 'saved', 'cwd': cwd})
                    retry = False
                except RuntimeError as error:
                    retry = 'fixture factory failure' in str(error)
                observations.append({'mode': mode, 'hidden': hidden, 'duplicateRejected': duplicate,
                    'firstRejected': first_rejected, 'retryReachedFactory': calls == 1, 'retryRejected': retry, 'factoryCalls': calls})
            if mode == 'shared-close':
                created = await bridge.new_session(ctx, {'cwd': cwd})
                factory.idle_gate = asyncio.Event()
                first_close = asyncio.create_task(bridge.close_session(ctx, created))
                await asyncio.sleep(0)
                second_close = asyncio.create_task(bridge.close_session(ctx, created))
                try:
                    await bridge.prompt(ctx, dict(created, prompt=[{'type': 'text', 'text': 'late'}]))
                    refused = False
                except ValueError as error:
                    refused = 'session is closing' in str(error)
                factory.idle_gate.set()
                results = await asyncio.gather(first_close, second_close)
                observations.append({'mode': mode, 'results': results, 'refused': refused,
                    'userCancels': len(factory.cancelled), 'agentGone': factory.get(created['sessionId']) is None})
            if mode == 'close-failure':
                created = await bridge.new_session(ctx, {'cwd': cwd})
                factory.failures['idle'] = RuntimeError('fixture idle failure')
                try:
                    await bridge.close_session(ctx, created)
                    reported = False
                except RuntimeError as error:
                    reported = 'session close failed' in str(error) and 'fixture idle failure' in str(error)
                listed = await bridge.list_sessions(ctx, {})
                observations.append({'mode': mode, 'reported': reported, 'agentGone': factory.get(created['sessionId']) is None,
                                     'listedIdentity': listed['sessions'][0]['sessionId'] == created['sessionId']})
        finally:
            await bridge.close(ctx)
            await dispose_context(ctx)
    return observations


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observe()), ensure_ascii=False, indent=2), encoding='utf-8')
