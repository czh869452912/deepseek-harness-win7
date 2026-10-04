import asyncio
from functools import lru_cache
import math
import ntpath
import re
import time
import uuid

from dsh.session.sqlite_database import SqliteDatabase, DatabaseError, load_sqlite
from dsh.session.text import WHITESPACE, trim_text

from dsh.session.sqlite_sql import sql

SCHEMA_VERSION = 19
APPLICATION_ID = 1146308688
UUID_PATTERN = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', re.I)


def field(row, key, kind, nullable=False, nonnegative=False, nonempty=False):
    if not isinstance(row, (dict, list)):
        raise ValueError('SQLite row must be an object')
    value = row.get(key) if isinstance(row, dict) else None
    if nullable and value is None and key in row:
        return None
    if kind == 'integer':
        valid = type(value) in (int, float) and math.isfinite(value) and int(value) == value and abs(value) <= 9007199254740991
        label = 'a safe integer'
    elif kind == 'string':
        valid, label = isinstance(value, str), 'a string'
    elif kind == 'blob':
        valid, label = isinstance(value, bytes), 'a blob'
    else:
        valid, label = isinstance(value, (str, bytes)), 'a string or blob'
    if not valid:
        raise ValueError('stored %s must be %s%s' % (key, label, ' or null' if nullable else ''))
    if nonnegative and value < 0:
        raise ValueError('stored ' + key + ' must be non-negative' + (' or null' if nullable else ''))
    if nonempty and len(value) == 0:
        raise ValueError('stored ' + key + ' must not be empty')
    return value


def decode_store_identity(row):
    value = field(row, 'store_id', 'string', nonempty=True)
    if not UUID_PATTERN.fullmatch(value):
        raise ValueError('stored store_id must be a UUID')
    return value


def decode_session_row(row):
    if not isinstance(row, (dict, list)):
        raise ValueError('stored session metadata must be an object')
    identity = field(row, 'id', 'string', nonempty=True)
    version = field(row, 'version', 'integer')
    cwd = field(row, 'cwd', 'string', nullable=True)
    if cwd is not None and not ntpath.isabs(cwd):
        raise ValueError('stored session cwd must be absolute')
    parent = field(row, 'parent_session', 'string', nullable=True)
    origin = field(row, 'origin', 'string', nullable=True)
    if origin not in (None, 'subagent'):
        raise ValueError('stored session origin must be subagent or null')
    incarnation = field(row, 'incarnation', 'string', nonempty=True)
    if not UUID_PATTERN.fullmatch(incarnation):
        raise ValueError('stored session incarnation must be a UUID')
    return dict(id=identity, version=version, created_at=field(row, 'created_at', 'integer', nonnegative=True), cwd=cwd,
                parent_session=parent, seed_length=field(row, 'seed_length', 'integer', nullable=True, nonnegative=True),
                origin=origin, delegation_depth=field(row, 'delegation_depth', 'integer', nullable=True, nonnegative=True),
                agent_preset=field(row, 'agent_preset', 'string', nullable=True), incarnation=incarnation,
                revision=field(row, 'revision', 'integer', nonnegative=True))


def decode_event_row(row):
    if not isinstance(row, (dict, list)):
        raise ValueError('stored event must be an object')
    packed = field(row, 'is_packed', 'integer')
    if packed not in (0, 1):
        raise ValueError('stored event is_packed must be 0 or 1')
    return dict(seq=field(row, 'seq', 'integer', nonnegative=True), type=field(row, 'type', 'string', nonempty=True),
                time=field(row, 'time', 'integer'), data=field(row, 'data', 'data'),
                source_event_seqs=field(row, 'source_event_seqs', 'blob', nullable=True),
                surface_op=field(row, 'surface_op', 'string', nullable=True), is_packed=packed)


def row_to_meta(row):
    value = dict(version=row['version'], id=row['id'], createdAt=row['created_at'])
    for source, target in (('cwd', 'cwd'), ('parent_session', 'parentSession'), ('seed_length', 'seedLength'),
                           ('origin', 'origin'), ('delegation_depth', 'delegationDepth'), ('agent_preset', 'agentPreset')):
        if row[source] is not None:
            value[target] = row[source]
    return value


def schema_objects(database):
    rows = database.prepare(sql('select-schema-objects')).all()
    pattern = WHITESPACE + '+'
    return [dict(type=field(row, 'type', 'string'), name=field(row, 'name', 'string'),
                 tbl_name=field(row, 'tbl_name', 'string'), sql=trim_text(re.sub(pattern, ' ', field(row, 'sql', 'string'))))
            for row in rows]


@lru_cache(maxsize=1)
def expected_schema():
    reference = SqliteDatabase(':memory:')
    try:
        reference.exec(sql('foreign-keys-on'))
        reference.exec(sql('schema'))
        return schema_objects(reference)
    finally:
        reference.close()


def validate_required_schema(database, path):
    if schema_objects(database) != expected_schema():
        raise ValueError('session database at "%s" does not contain the required schema objects' % path)


def validate_mutation(database, path):
    version = field(database.prepare(sql('select-user-version')).get(), 'user_version', 'integer')
    application = field(database.prepare(sql('select-application-id')).get(), 'application_id', 'integer')
    if application != APPLICATION_ID:
        raise ValueError('session database application id changed before mutation (expected %d, got %d)' % (APPLICATION_ID, application))
    validate_required_schema(database, path)
    if version != SCHEMA_VERSION:
        raise ValueError('session database schema changed before mutation (expected %d, got %d)' % (SCHEMA_VERSION, version))


async def open_database(path, journal_mode='wal', busy_timeout_ms=5000):
    load_sqlite()
    deadline = time.monotonic() + busy_timeout_ms / 1000
    database = SqliteDatabase(path)
    try:
        database.exec('PRAGMA busy_timeout = %d' % busy_timeout_ms)
        database.exec(sql('trusted-schema-off'))
        if field(database.prepare(sql('select-trusted-schema')).get(), 'trusted_schema', 'integer') != 0:
            value = database.prepare(sql('select-trusted-schema')).get()['trusted_schema']
            raise ValueError('session database at "%s" retained trusted_schema=%s, expected 0' % (path, value))
        database.exec(sql('mmap-off'))
        if path != ':memory:' and field(database.prepare(sql('select-mmap-size')).get(), 'mmap_size', 'integer') != 0:
            value = database.prepare(sql('select-mmap-size')).get()['mmap_size']
            raise ValueError('session database at "%s" retained mmap_size=%s, expected 0' % (path, value))
        database.exec(sql('page-size'))
        database.exec(sql('foreign-keys-on'))
        began = False
        try:
            database.exec(sql('begin-immediate'))
            began = True
            version = field(database.prepare(sql('select-user-version')).get(), 'user_version', 'integer')
            application = field(database.prepare(sql('select-application-id')).get(), 'application_id', 'integer')
            count = field(database.prepare(sql('select-user-object-count')).get(), 'count', 'integer')
            if version == 0 and (application != 0 or count > 0):
                raise ValueError('session database at "%s" has an unversioned schema or application identity' % path)
            if version != 0 and version != SCHEMA_VERSION:
                raise ValueError('session database at "%s" has schema version %d, incompatible with this build (%d)' % (path, version, SCHEMA_VERSION))
            if version != 0 and application != APPLICATION_ID:
                raise ValueError('session database at "%s" has application id %d, expected %d' % (path, application, APPLICATION_ID))
            if version == 0:
                database.exec(sql('schema'))
                database.prepare(sql('insert-persistence-state')).run(str(uuid.uuid4()))
                database.exec(sql('set-application-id'))
                database.exec(sql('set-user-version-19'))
            validate_required_schema(database, path)
            database.exec(sql('commit'))
            began = False
        except BaseException:
            if began:
                try:
                    database.exec(sql('rollback'))
                except Exception:
                    pass
            raise
        while True:
            try:
                selected = database.prepare(sql('journal-mode-' + journal_mode)).get()['journal_mode']
                break
            except DatabaseError as error:
                remaining = max(0, math.ceil((deadline - time.monotonic()) * 1000))
                if error.code != 5 or remaining == 0:
                    raise
                await asyncio.sleep(min(10, remaining) / 1000)
                if time.monotonic() >= deadline:
                    raise
        expected = 'memory' if path == ':memory:' else journal_mode
        if selected.lower() != expected:
            raise ValueError('session database at "%s" selected journal mode %s, expected %s' % (path, selected.lower(), expected))
        database.exec(sql('synchronous-full'))
        if field(database.prepare(sql('select-synchronous')).get(), 'synchronous', 'integer') != 2:
            value = database.prepare(sql('select-synchronous')).get()['synchronous']
            raise ValueError('session database at "%s" retained synchronous=%s, expected FULL (2)' % (path, value))
        return database
    except BaseException:
        database.close()
        raise
