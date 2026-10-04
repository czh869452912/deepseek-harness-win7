import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(sys.argv[sys.argv.index('--root') + 1]).resolve() if '--root' in sys.argv else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.cordis import Context
from dsh.core.session import SessionHeader
from dsh.core.session import SessionPlugin
from dsh.session.persistence_sqlite_canonical import SqliteSessionPersistencePlugin


async def observe(path):
    assert not path.exists()
    context = Context()
    await context.plugin(SessionPlugin)
    await context.plugin(SqliteSessionPersistencePlugin, dict(path=str(path)))
    persistence = context.get('sessionPersistence')
    assert not path.exists()
    meta = SessionHeader('cold-packed', created_at=1234, cwd=str(ROOT))
    events = [dict(type='turn/start', seq=0, time=0, data=dict(turn=1)),
              dict(type='step/start', seq=1, time=1, data=dict(turn=1, step=1))]
    events.extend(dict(type='assistant/chunk', seq=index + 2, time=index + 2,
                       data=dict(turn=1, step=1, chunk=dict(type='text-delta', index=0, text='piece')))
                  for index in range(100))
    await persistence.create(meta)
    await persistence.append(meta.id, events)
    stored = await persistence.store.load_stored(meta.id)
    key = persistence.store.session_key(meta.id)
    from dsh.session.sqlite_schema import sql
    persistence.store.database.prepare(sql('insert-event')).run(key, 102, 'text-chunks', 102, '{invalid', None, None, 1)
    before = await persistence.stored_revision(meta.id)
    inspected = await persistence.inspect(meta.id)
    assert len(inspected.events) == 104
    assert await persistence.stored_revision(meta.id) == before
    loaded = await persistence.load(meta.id)
    assert len(loaded.events) == 104
    assert await persistence.stored_revision(meta.id) != before
    assert 'tornMarker' not in await persistence.store.load_stored(meta.id)
    await context.fiber.dispose()
    next_context = Context()
    await next_context.plugin(SessionPlugin)
    await next_context.plugin(SqliteSessionPersistencePlugin, dict(path=str(path)))
    next_persistence = next_context.get('sessionPersistence')
    cold = await next_persistence.prepare(meta.id)
    assert len(cold.session.events) == 105
    assert cold.session.events[-1]['type'] == 'session/end-seed' and cold.session.events[-1]['seq'] == 104
    assert len((await next_persistence.read_stored(meta.id)).events) == 104
    assert next_context.get('sessions').get(meta.id) is None
    cold.dispose()
    suffix = await next_persistence.read_from(meta.id, 50)
    assert suffix.events[0]['seq'] == 50 and len(suffix.events) == 54
    await next_context.fiber.dispose()
    return dict(lazy=True, inspected=104, recovered=104, coldPrepared=105, stored=104, endSeedSeq=104, suffix=54, unpublished=True)



