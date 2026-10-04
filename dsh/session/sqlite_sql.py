from functools import lru_cache
import hashlib
import json
from pathlib import Path


SQL_RESOURCES = (
    'begin', 'begin-immediate', 'commit', 'delete-events-from', 'foreign-keys-on',
    'insert-event', 'insert-persistence-state', 'journal-mode-delete', 'journal-mode-persist',
    'journal-mode-truncate', 'journal-mode-wal', 'mmap-off', 'page-size', 'rollback', 'schema',
    'select-application-id', 'select-events', 'select-events-from', 'select-mmap-size',
    'select-packed-predecessors', 'select-schema-objects', 'select-session', 'select-session-key',
    'select-sessions', 'select-store-id', 'select-synchronous', 'select-tail-events',
    'select-trusted-schema', 'select-user-object-count', 'select-user-version',
    'set-application-id', 'set-user-version-19', 'synchronous-full', 'trusted-schema-off',
    'update-session-revision', 'upsert-session',
)
SQL_MANIFEST_SHA256 = 'c1c69a22095372773e9945ee39be875f4d695e784e09a4bd256302ef1b9eb48c'


def verify_sql_files(directory):
    directory = Path(directory)
    content = (directory / 'manifest.json').read_bytes()
    if hashlib.sha256(content).hexdigest() != SQL_MANIFEST_SHA256:
        raise RuntimeError('SQLite SQL manifest hash differs')
    manifest = json.loads(content.decode('utf-8'))
    if set(manifest) != {name + '.sql' for name in SQL_RESOURCES}:
        raise RuntimeError('SQLite SQL resource inventory differs')
    for name, expected in manifest.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('SQLite SQL resource hash differs: ' + name)
    return manifest


@lru_cache(maxsize=1)
def _manifest():
    directory = Path(__file__).with_name('resources') / 'sql'
    content = (directory / 'manifest.json').read_bytes()
    if hashlib.sha256(content).hexdigest() != SQL_MANIFEST_SHA256:
        raise RuntimeError('SQLite SQL manifest hash differs')
    value = json.loads(content.decode('utf-8'))
    if set(value) != {name + '.sql' for name in SQL_RESOURCES}:
        raise RuntimeError('SQLite SQL resource inventory differs')
    return value


@lru_cache(maxsize=36)
def sql(name):
    if name not in SQL_RESOURCES:
        raise ValueError('Unknown SQLite resource: ' + str(name))
    filename = name + '.sql'
    content = (Path(__file__).with_name('resources') / 'sql' / filename).read_bytes()
    if hashlib.sha256(content).hexdigest() != _manifest()[filename]:
        raise RuntimeError('SQLite SQL resource hash differs: ' + filename)
    return content.decode('utf-8')
