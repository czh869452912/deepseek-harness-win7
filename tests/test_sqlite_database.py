import sqlite3

import pytest

from dsh.session.sqlite_database import DatabaseError, SqliteDatabase


def test_pinned_database_coexists_with_loaded_stdlib_and_enforces_strict_types():
    legacy_version = sqlite3.sqlite_version
    database = SqliteDatabase(':memory:')
    try:
        assert database.prepare('SELECT sqlite_version() AS version').get() == {'version': '3.51.2'}
        assert sqlite3.sqlite_version == legacy_version
        database.exec('CREATE TABLE values_probe(value INTEGER NOT NULL) STRICT')
        database.prepare('INSERT INTO values_probe VALUES (?)').run(7)
        with pytest.raises(DatabaseError) as raised:
            database.prepare('INSERT INTO values_probe VALUES (?)').run('not an integer')
        assert raised.value.code == 3091
        assert database.prepare('SELECT value FROM values_probe').all() == [{'value': 7}]
    finally:
        database.close()


@pytest.mark.parametrize('value', [None, -9223372036854775808, 9223372036854775807,
    1.25, '中文\0😀', b'\0\xff', b'', '', bytearray(b'abc'), memoryview(b'abc')])
def test_pinned_database_preserves_bound_storage_values(value):
    database = SqliteDatabase(':memory:')
    try:
        expected = bytes(value) if isinstance(value, (bytearray, memoryview)) else value
        assert database.prepare('SELECT ? AS value').get(value) == {'value': expected}
    finally:
        database.close()


def test_pinned_database_fts5_unicode61_rank_and_highlight():
    database = SqliteDatabase(':memory:')
    try:
        database.exec("CREATE VIRTUAL TABLE docs USING fts5(text, tokenize='unicode61')")
        insert = database.prepare('INSERT INTO docs VALUES (?)')
        insert.run('café CAFÉ')
        insert.run('cafe')
        rows = database.prepare("SELECT highlight(docs,0,'[',']') AS snippet, bm25(docs) AS rank "
                                'FROM docs WHERE docs MATCH ? ORDER BY rank').all('cafe')
        assert {row['snippet'] for row in rows} == {'[café] [CAFÉ]', '[cafe]'}
        assert all(row['rank'] < 0 for row in rows)
    finally:
        database.close()


def test_pinned_database_failed_statement_finalizes_and_transaction_rolls_back(tmp_path):
    path = tmp_path / '中文.sqlite'
    database = SqliteDatabase(str(path))
    database.exec('CREATE TABLE values_probe(value INTEGER PRIMARY KEY) STRICT')
    database.exec('BEGIN IMMEDIATE')
    try:
        database.prepare('INSERT INTO values_probe VALUES (?)').run(1)
        with pytest.raises(DatabaseError):
            database.prepare('INSERT INTO values_probe VALUES (?)').run(1)
        database.exec('ROLLBACK')
        assert database.prepare('SELECT * FROM values_probe').all() == []
        for attempt in range(100):
            with pytest.raises(ValueError):
                database.prepare('SELECT ?').get()
        assert database.prepare('PRAGMA integrity_check').get() == {'integrity_check': 'ok'}
    finally:
        database.close()
    path.rename(tmp_path / 'retired.sqlite')
    (tmp_path / 'retired.sqlite').unlink()


@pytest.mark.parametrize('value', [True, 9223372036854775808, {}, []])
def test_pinned_database_refuses_unsupported_bindings_without_retaining_statement(value):
    database = SqliteDatabase(':memory:')
    try:
        with pytest.raises((TypeError, OverflowError)):
            database.prepare('SELECT ?').get(value)
        assert database.prepare('SELECT 1 AS value').get() == {'value': 1}
    finally:
        database.close()


def test_pinned_database_refuses_multi_statement_and_nul_sql_then_retires():
    database = SqliteDatabase(':memory:')
    try:
        with pytest.raises(ValueError):
            database.prepare('SELECT 1; SELECT 2').get()
        with pytest.raises(ValueError):
            database.exec('SELECT 1\0')
        assert database.prepare('SELECT 1 WHERE 0').get() is None
    finally:
        database.close()
    database.close()
    with pytest.raises(RuntimeError, match='closed'):
        database.prepare('SELECT 1')
