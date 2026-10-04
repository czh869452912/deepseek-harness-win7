import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile


def observe(root):
    sys.path.insert(0, str(root))
    import dsh
    from dsh.session.query_schema import open_search_database
    from dsh.session.sqlite_database import DatabaseError, SqliteDatabase, _library
    rows = []
    with tempfile.TemporaryDirectory(prefix='dsh-query-schema-') as directory:
        path_root = Path(directory)
        database = open_search_database(':memory:', 'wal')
        try:
            names = {'live_sessions', 'persisted_sessions', 'search_state'}
            rows.append(dict(name='memory-schema', observed=dict(
                application=database.prepare('PRAGMA application_id').get()['application_id'],
                version=database.prepare('PRAGMA user_version').get()['user_version'],
                strict=sorted([dict(name=row['name'], strict=row['strict'])
                    for row in database.prepare('PRAGMA table_list').all() if row['name'] in names],
                    key=lambda row: row['name']),
                persistedColumns=[row['name'] for row in database.prepare('PRAGMA table_info(persisted_docs)').all()],
                liveColumns=[row['name'] for row in database.prepare('PRAGMA temp.table_info(live_docs)').all()])))
        finally:
            database.close()
        for name, sql in [
            ('strict-type', "UPDATE search_state SET global_generation = 'bad'"),
            ('singleton-check', 'INSERT INTO search_state VALUES(2,0)'),
            ('live-check', "INSERT INTO temp.live_sessions(id,version,created_at,fingerprint,persisted,generation) VALUES('a',1,1,'f',2,1)"),
            ('strict-null', "INSERT INTO persisted_sessions(id,version,created_at,revision,generation) VALUES(NULL,1,1,'r',1)"),
        ]:
            database = open_search_database(':memory:', 'wal')
            try:
                code = 0
                try:
                    database.prepare(sql).run()
                except DatabaseError as error:
                    code = error.code
                rows.append(dict(name=name, observed=dict(code=code,
                    generation=database.prepare('SELECT global_generation FROM search_state').get()['global_generation'])))
            finally:
                database.close()
        database = open_search_database(':memory:', 'wal')
        try:
            database.prepare('INSERT INTO persisted_docs VALUES(?,?,?,?,?,?,?)').run(
                'café 中文 😀', 'session', 2, 'message', 5, 'current', 9)
            rows.append(dict(name='memory-documents', observed=dict(
                matches=database.prepare('SELECT session_id,codepoint_length FROM persisted_docs WHERE persisted_docs MATCH ?').all('cafe'),
                text=database.prepare('SELECT text FROM persisted_docs').get()['text'])))
        finally:
            database.close()
        for mode in ('wal', 'delete', 'truncate', 'persist'):
            database = open_search_database(str(path_root / mode / '中文.sqlite'), mode)
            try:
                rows.append(dict(name='file-' + mode, observed=dict(
                    mode=database.prepare('PRAGMA journal_mode').get()['journal_mode'],
                    version=database.prepare('PRAGMA user_version').get()['user_version'])))
            finally:
                database.close()
        for kind in ('reopen', 'upgrade', 'same-version', 'live-scope'):
            path = path_root / (kind + '.sqlite')
            database = open_search_database(str(path), 'delete')
            database.exec('UPDATE search_state SET global_generation = 7')
            database.prepare('INSERT INTO persisted_docs VALUES(?,?,?,?,?,?,?)').run(
                'café 中文 😀', 'session', 2, 'message', 5, 'current', 9)
            database.prepare('INSERT INTO temp.live_docs VALUES(?,?,?,?,?,?,?)').run(
                'live', 'session', 3, 'message', 6, 'current', 4)
            if kind == 'upgrade':
                database.exec('PRAGMA user_version = 7')
            database.close()
            database = open_search_database(str(path), 'delete')
            try:
                rows.append(dict(name=kind, observed=dict(
                    generation=database.prepare('SELECT global_generation FROM search_state').get()['global_generation'],
                    persisted=database.prepare('SELECT count(*) AS count FROM persisted_docs').get()['count'],
                    live=database.prepare('SELECT count(*) AS count FROM temp.live_docs').get()['count'],
                    matches=[row['session_id'] for row in database.prepare(
                        'SELECT session_id FROM persisted_docs WHERE persisted_docs MATCH ?').all('cafe')])))
            finally:
                database.close()
        for kind in ('foreign-app', 'unmarked-nonempty', 'unknown-derived', 'canonical', 'corrupt'):
            path = path_root / (kind + '.sqlite')
            if kind == 'corrupt':
                path.write_text('not a SQLite database', encoding='utf-8')
            else:
                database = SqliteDatabase(str(path))
                database.exec("CREATE TABLE sentinel(value TEXT); INSERT INTO sentinel VALUES('owned')")
                if kind == 'foreign-app':
                    database.exec('PRAGMA application_id = 1234')
                if kind == 'unknown-derived':
                    database.exec('PRAGMA application_id = 1146308689; PRAGMA user_version = 7')
                if kind == 'canonical':
                    database.exec('PRAGMA application_id = 1146308688; PRAGMA user_version = 19')
                database.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            message = ''
            try:
                database = open_search_database(str(path), 'wal')
                database.close()
            except Exception as error:
                message = str(error).replace(str(path), '<path>')
            rows.append(dict(name=kind, observed=dict(message=message,
                unchanged=before == hashlib.sha256(path.read_bytes()).hexdigest())))
    library = _library()
    binary = root / 'dsh/session/bin/sqlite3.dll'
    return dict(observations=rows, root=str(root), module=str(Path(dsh.__file__).resolve()),
                python=list(sys.version_info[:3]), sqlite=dict(
                    version=library.sqlite3_libversion().decode('ascii'),
                    sourceId=library.sqlite3_sourceid().decode('ascii'), dll=str(binary),
                    sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    args.output.write_text(json.dumps(observe(args.root.resolve()), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
