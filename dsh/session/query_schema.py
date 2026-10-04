import os

from dsh.session.sqlite_database import SqliteDatabase


SESSION_QUERY_SQLITE_SCHEMA_VERSION = 8
SESSION_QUERY_SQLITE_APPLICATION_ID = 0x44534851
DERIVED_USER_TABLES = {
    'search_state', 'persisted_sessions', 'persisted_docs', 'persisted_docs_data',
    'persisted_docs_idx', 'persisted_docs_content', 'persisted_docs_docsize', 'persisted_docs_config',
}
JOURNAL_MODES = {'wal', 'delete', 'truncate', 'persist'}


def open_search_database(path, journal_mode):
    if journal_mode not in JOURNAL_MODES:
        raise ValueError('Invalid session-search journal mode')
    actual = path if path == ':memory:' else os.path.abspath(path)
    if actual != ':memory:':
        os.makedirs(os.path.dirname(actual), mode=0o700, exist_ok=True)
        try:
            descriptor = os.open(actual, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
    database = SqliteDatabase(actual)
    try:
        application_id = database.prepare('PRAGMA application_id').get()['application_id']
        version = database.prepare('PRAGMA user_version').get()['user_version']
        tables = [row['name'] for row in database.prepare(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT GLOB 'sqlite_*' ORDER BY name").all()]
        if application_id != 0 and application_id != SESSION_QUERY_SQLITE_APPLICATION_ID:
            raise RuntimeError('session-search database at "{}" belongs to another application'.format(actual))
        if application_id == 0 and tables:
            raise RuntimeError('session-search database at "{}" is not an empty or recognized derived index'.format(actual))
        if application_id == SESSION_QUERY_SQLITE_APPLICATION_ID:
            unknown = [name for name in tables if name not in DERIVED_USER_TABLES]
            if unknown:
                raise RuntimeError('session-search database at "{}" has unrecognized user tables: {}'.format(
                    actual, ', '.join(unknown)))
            if version != SESSION_QUERY_SQLITE_SCHEMA_VERSION:
                for name in tables:
                    database.exec('DROP TABLE IF EXISTS "{}"'.format(name.replace('"', '""')))
                database.exec('PRAGMA user_version = 0')
        database.exec('PRAGMA journal_mode = ' + journal_mode.upper())
        _persistent_schema(database)
        _temporary_schema(database)
        return database
    except BaseException:
        database.close()
        raise


def _persistent_schema(database):
    database.exec('PRAGMA application_id = {}'.format(SESSION_QUERY_SQLITE_APPLICATION_ID))
    database.exec('''
        CREATE TABLE IF NOT EXISTS search_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            global_generation INTEGER NOT NULL
        ) STRICT
    ''')
    database.exec('INSERT OR IGNORE INTO search_state (singleton, global_generation) VALUES (1, 0)')
    database.exec('''
        CREATE TABLE IF NOT EXISTS persisted_sessions (
            id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            cwd TEXT,
            parent_session TEXT,
            seed_length INTEGER,
            delegation_depth INTEGER,
            agent_preset TEXT,
            revision TEXT NOT NULL,
            generation INTEGER NOT NULL
        ) STRICT
    ''')
    database.exec('''
        CREATE VIRTUAL TABLE IF NOT EXISTS persisted_docs USING fts5(
            text,
            session_id UNINDEXED,
            seq UNINDEXED,
            type UNINDEXED,
            time UNINDEXED,
            surface UNINDEXED,
            codepoint_length UNINDEXED,
            tokenize = 'unicode61'
        )
    ''')
    database.exec('PRAGMA user_version = {}'.format(SESSION_QUERY_SQLITE_SCHEMA_VERSION))


def _temporary_schema(database):
    database.exec('''
        CREATE TEMP TABLE IF NOT EXISTS live_sessions (
            id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            cwd TEXT,
            parent_session TEXT,
            seed_length INTEGER,
            delegation_depth INTEGER,
            agent_preset TEXT,
            fingerprint TEXT NOT NULL,
            persisted INTEGER NOT NULL CHECK (persisted IN (0, 1)),
            generation INTEGER NOT NULL
        ) STRICT
    ''')
    database.exec('''
        CREATE VIRTUAL TABLE IF NOT EXISTS temp.live_docs USING fts5(
            text,
            session_id UNINDEXED,
            seq UNINDEXED,
            type UNINDEXED,
            time UNINDEXED,
            surface UNINDEXED,
            codepoint_length UNINDEXED,
            tokenize = 'unicode61'
        )
    ''')
