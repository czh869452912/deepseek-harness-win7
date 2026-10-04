import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


arguments = argparse.ArgumentParser()
arguments.add_argument('output', type=Path)
arguments.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
options = arguments.parse_args()
ROOT = options.root.resolve()
sys.path.insert(0, str(ROOT))

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.session import SessionHeader, SessionPlugin
from dsh.session.query_engine import SqliteSessionQueryEngine
from dsh.session.sqlite_database import _library


def event(text, seq=0):
    return dict(type='user/message', seq=seq, time=seq+1, surfaceOp='append',
                data=dict(id='message-'+str(seq), role='user', content=[dict(type='text', text=text)], source=dict(kind='user')))


def sessions(page):
    return [dict(id=item['header'].id, live=item['live'], persisted=item['persisted'],
                 seq=item['bestMatch']['seq'], snippet=item['bestMatch']['snippet']) for item in page['items']]


async def main():
    rows = []
    def record(name, observed):
        rows.append(dict(name=name, observed=observed))
    context = Context()
    await context.plugin(SessionPlugin)
    entries = dict(alpha=dict(header=SessionHeader('alpha', created_at=1), revision='1', events=[event('needle needle')]),
                   beta=dict(header=SessionHeader('beta', created_at=1), revision='2', events=[event('needle')]))
    class Persistence:
        inspected = 0
        snapshots = 0
        unstable = 0
        async def listSnapshots(self, signal=None):
            self.snapshots += 1
            if self.unstable > 0:
                entries['alpha']['revision'] = str(100+self.snapshots)
                self.unstable -= 1
            return [dict(header=copy.deepcopy(entry['header']), revision=entry['revision']) for entry in entries.values()]
        async def inspect(self, session_id, signal=None):
            self.inspected += 1
            entry = entries[session_id]
            return dict(meta=copy.deepcopy(entry['header']), events=copy.deepcopy(entry['events']))
    persistence = Persistence()
    provider = context.provide('sessionPersistence', persistence)
    query = SqliteSessionQueryEngine(context, dict(path=':memory:', openAt='first-search', defaultLimit=1, maxLimit=2))
    try:
        first = await query.searchSessions(dict(query='needle'))
        record('persisted-ranked', sessions(first))
        record('persisted-next-page', sessions(await query.searchSessions(dict(query='needle', cursor=first['nextCursor']))))
        inspections = persistence.inspected
        record('unchanged-no-inspect', dict(items=sessions(await query.searchSessions(dict(query='needle'))),
                                           inspections=persistence.inspected-inspections))
        events = await query.searchEvents(dict(sessionId='alpha', query='needle'))
        record('event-header', dict(header=events['session'].to_dict(), items=events['items']))
        entries['alpha']['events'].append(event('needle newest', 1))
        entries['alpha']['revision'] = '3'
        async def refused(name, operation, **extra):
            try:
                await operation
                raise AssertionError('expected refusal')
            except Exception as error:
                record(name, dict(code=getattr(error, 'code', None), message=getattr(error, 'message', str(error)), **extra))
        await refused('cross-session-stale', query.searchSessions(dict(query='needle', cursor=first['nextCursor'])))
        changed = await query.searchEvents(dict(sessionId='alpha', query='needle'))
        record('event-page', dict(seqs=[item['seq'] for item in changed['items']], hasNext='nextCursor' in changed))
        entries['beta']['events'].append(event('needle outside', 1))
        entries['beta']['revision'] = '4'
        continued = await query.searchEvents(dict(sessionId='alpha', query='needle', cursor=changed['nextCursor']))
        record('unrelated-event-cursor', dict(seqs=[item['seq'] for item in continued['items']]))
        live = context.get('sessions').prepare('alpha', seed=[event('needle LIVE')], meta=dict(createdAt=1))
        detach = context.get('sessions').enter(live)
        context.get('sessions').announce(live)
        record('live-preference', sessions(await query.searchSessions(dict(query='needle', limit=2))))
        record('literal-operators', sessions(await query.searchSessions(dict(query='needle OR unrelated', limit=2))))
        record('empty-availability', sessions(await query.searchSessions(dict(query='needle', sessionFilters=[dict(kind='availability', values=[])]))))
        persistence.unstable = 2
        before_retry = persistence.inspected
        record('one-stable-retry', dict(items=sessions(await query.searchSessions(dict(query='needle', limit=2))),
                                       inspections=persistence.inspected-before_retry))
        detach()
        await query.searchSessions(dict(query='needle'))
        persistence.unstable = 4
        await refused('unstable-refusal', query.searchSessions(dict(query='needle')))
        persistence.unstable = 0
        provider()
        record('unmounted-hidden', sessions(await query.searchSessions(dict(query='needle', limit=2))))
        replacement_service = Persistence()
        replacement = context.provide('sessionPersistence', replacement_service)
        record('replacement-reloads', dict(items=sessions(await query.searchSessions(dict(query='needle', limit=2))),
                                           inspections=replacement_service.inspected))
        replacement()
        controller = AbortController()
        controller.abort(TypeError('reason'))
        before_abort = replacement_service.snapshots
        await refused('preabort-zero-observation', query.searchSessions(dict(query='needle'), dict(signal=controller.signal)),
                      snapshots=replacement_service.snapshots-before_abort)
        await query.close()
        await refused('closed-refusal', query.searchSessions(dict(query='needle')))
    finally:
        await query.close()
        await context.fiber.dispose()
    import dsh.session.query_engine as implementation
    library = _library()
    manifest = json.loads((ROOT / 'dsh/session/bin/sqlite3.json').read_text(encoding='utf-8'))
    report = dict(observations=rows, root=str(ROOT), moduleFile=str(Path(implementation.__file__).resolve()),
                  python=sys.version.split()[0], sqliteVersion=library.sqlite3_libversion().decode('utf-8'),
                  sqliteSourceId=library.sqlite3_sourceid().decode('utf-8'),
                  sqliteDllSha256=hashlib.sha256((ROOT / 'dsh/session/bin/sqlite3.dll').read_bytes()).hexdigest(),
                  manifest=manifest)
    options.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
