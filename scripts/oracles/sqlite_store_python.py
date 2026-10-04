import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(sys.argv[sys.argv.index('--root') + 1]).resolve() if '--root' in sys.argv else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.session.sqlite_store import SqliteStore
from dsh.session.sqlite_schema import sql
from dsh.session.sqlite_database import SqliteDatabase


def chunk(sequence):
    return dict(type='assistant/chunk', seq=sequence, time=sequence,
                data=dict(turn=1, step=1, chunk=dict(type='text-delta', index=0, text='界' * 100)))


def visible(value):
    if isinstance(value, dict):
        return {key: visible(item) for key, item in value.items() if key != 'revision'}
    if isinstance(value, list):
        return [visible(item) for item in value]
    return value


async def observe(directory, mode):
    meta = dict(id='store-session', version=0, createdAt=1234, cwd=str(directory), origin='subagent',
                delegationDepth=2, agentPreset='standard')
    if mode == 'produce':
        store = SqliteStore(str(directory / 'native.db'), journal_mode='delete')
        try:
            await store.validate_path()
            assert not (directory / 'native.db').exists()
            await store.append_batch(meta, [chunk(sequence) for sequence in range(2051)], False)
            (directory / 'native-file-initial-revision.txt').write_text(await store.read_revision(meta['id']), encoding='utf-8')
        finally:
            await store.close()
        return
    store = SqliteStore(str(directory / 'source.db'), journal_mode='delete')
    rows = []
    async def capture(name, operation):
        try:
            rows.append(dict(name=name, value=visible(await operation())))
        except Exception as error:
            rows.append(dict(name=name, error=str(error)))
    try:
        rows.append(dict(name='exact-cross-file-revision', value=await store.read_revision(meta['id']) ==
                         (directory / 'source-file-initial-revision.txt').read_text(encoding='utf-8')))
        await capture('source-cross-read', lambda: store.load_stored(meta['id']))
        await capture('source-cross-suffix', lambda: store.load_stored_from(meta['id'], 1025))
        await capture('source-cross-list', lambda: store.list())
        await capture('source-cross-snapshots', lambda: store.list_snapshots())
        before = await store.read_revision(meta['id'])
        await store.append_batch(meta, [chunk(sequence) for sequence in range(2051, 2054)], True)
        after = await store.read_revision(meta['id'])
        rows.append(dict(name='revision-advanced-once', value=before.rsplit(':', 1)[0] == after.rsplit(':', 1)[0] and
                         int(after.rsplit(':', 1)[1]) == int(before.rsplit(':', 1)[1]) + 1))
        await capture('stale-append', lambda: store.append_batch(meta, [chunk(2051)], True))
        await capture('after-stale-append', lambda: store.load_stored_from(meta['id'], 2051))
        await capture('stale-repair', lambda: store.commit_repair(meta, None, [dict(type='turn/end', seq=1, time=1, data=dict(turn=1))]))
        await capture('after-stale-repair', lambda: store.load_stored_from(meta['id'], 2051))
        store.database.exec('PRAGMA application_id=12345')
        await capture('ownership-changed-append', lambda: store.append_batch(meta, [chunk(2054)], True))
        store.database.exec(sql('set-application-id'))
        await capture('after-ownership-refusal', lambda: store.load_stored_from(meta['id'], 2051))
        rows.append(dict(name='page-size', value=store.database.prepare('PRAGMA page_size').get()['page_size']))
        rows.append(dict(name='physical-count', value=store.database.prepare('SELECT count(*) AS count FROM events').get()['count']))
        rows.append(dict(name='physical-kind', value=store.database.prepare('SELECT DISTINCT typeof(data) AS kind FROM events').all()))
    finally:
        await store.close()
    memory = SqliteStore(':memory:')
    torn_meta = dict(meta, id='torn-session')
    try:
        await memory.append_batch(torn_meta, [dict(type='turn/start', seq=0, time=0, data=dict(turn=1))], False)
        key = memory.session_key(torn_meta['id'])
        memory.database.prepare(sql('insert-event')).run(key, 1, 'text-chunks', 1, '{invalid', None, None, 1)
        await capture('torn-load', lambda: memory.load_stored(torn_meta['id']))
        await capture('torn-append-refusal', lambda: memory.append_batch(torn_meta, [chunk(1)], True))
        await capture('repair-missing-marker', lambda: memory.commit_repair(torn_meta, None, [dict(type='turn/end', seq=1, time=1, data=dict(turn=1))]))
        await memory.commit_repair(torn_meta, 1, [dict(type='turn/end', seq=1, time=1, data=dict(turn=1))])
        await capture('repaired-load', lambda: memory.load_stored(torn_meta['id']))
        await capture('repair-old-marker', lambda: memory.commit_repair(torn_meta, 1, []))
        memory.database.prepare(sql('insert-event')).run(key, 2, 'text-chunks', 2, '{invalid', None, None, 1)
        memory.database.prepare(sql('insert-event')).run(key, 3, 'turn/end', 3, '{"turn":1}', None, None, 0)
        await capture('committed-corruption', lambda: memory.load_stored(torn_meta['id']))
    finally:
        await memory.close()
    for mode in ('wal', 'delete', 'truncate', 'persist'):
        mode_store = SqliteStore(str(directory / ('native-' + mode + '.db')), journal_mode=mode)
        try:
            await mode_store.open()
            rows.append(dict(name='journal-' + mode, value=dict(mode=mode_store.database.prepare('PRAGMA journal_mode').get()['journal_mode'],
                sync=mode_store.database.prepare('PRAGMA synchronous').get()['synchronous'],
                page=mode_store.database.prepare('PRAGMA page_size').get()['page_size'],
                trusted=mode_store.database.prepare('PRAGMA trusted_schema').get()['trusted_schema'],
                mmap=mode_store.database.prepare('PRAGMA mmap_size').get()['mmap_size'])))
        finally:
            await mode_store.close()
    for name, setup in [('unversioned', 'CREATE TABLE unrelated (value TEXT)'),
                        ('old-version', 'PRAGMA user_version=18'), ('future-version', 'PRAGMA user_version=20'),
                        ('foreign-application', 'PRAGMA user_version=19; PRAGMA application_id=12345'),
                        ('altered-schema', 'PRAGMA user_version=19; PRAGMA application_id=1146308688; CREATE TABLE unrelated(value TEXT)')]:
        path = directory / ('native-refuse-' + name + '.db')
        foreign = SqliteDatabase(str(path))
        foreign.exec(setup)
        foreign.close()
        before = path.read_bytes()
        refused = SqliteStore(str(path))
        try:
            await refused.open()
            raise AssertionError('foreign database accepted')
        except ValueError as error:
            rows.append(dict(name='refuse-' + name, value=dict(message=str(error).replace(str(path), '<database>'), unchanged=path.read_bytes() == before)))
        finally:
            await refused.close()
    peer_path = directory / 'native-peers.db'
    first, second = SqliteStore(str(peer_path)), SqliteStore(str(peer_path))
    try:
        await first.materialize_header(meta)
        await second.open()
        initial = await second.read_revision(meta['id'])
        await first.append_batch(meta, [chunk(sequence) for sequence in range(3)], True)
        rows.append(dict(name='peer-revision-observed', value=await second.read_revision(meta['id']) != initial))
        await capture('peer-stale-append', lambda: second.append_batch(meta, [chunk(0)], True))
        await capture('peer-winning-tail', lambda: second.load_stored_from(meta['id'], 0))
    finally:
        await second.close()
        await first.close()
    (directory / 'native-observations.json').write_text(json.dumps(dict(rows=rows), ensure_ascii=True), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--mode', choices=('produce', 'consume'), required=True)
    args = parser.parse_args()
    asyncio.run(observe(args.directory.resolve(), args.mode))


if __name__ == '__main__':
    main()
