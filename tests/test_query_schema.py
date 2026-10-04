import pytest

from dsh.session import query_schema
from dsh.session.sqlite_database import DatabaseError, SqliteDatabase


def test_actual_query_schema_keeps_live_tables_local_to_each_connection(tmp_path):
    path = str(tmp_path / 'shared.sqlite')
    first = query_schema.open_search_database(path, 'wal')
    second = query_schema.open_search_database(path, 'wal')
    try:
        first.prepare('INSERT INTO temp.live_docs VALUES(?,?,?,?,?,?,?)').run('live', 'session', 1, 'message', 1, 'current', 4)
        first.exec('UPDATE search_state SET global_generation = 3')
        assert first.prepare('SELECT count(*) AS count FROM temp.live_docs').get() == {'count': 1}
        assert second.prepare('SELECT count(*) AS count FROM temp.live_docs').get() == {'count': 0}
        assert second.prepare('SELECT global_generation FROM search_state').get() == {'global_generation': 3}
    finally:
        first.close()
        second.close()


def test_actual_query_schema_rolls_back_main_and_temporary_fts_as_one_transaction():
    database = query_schema.open_search_database(':memory:', 'wal')
    try:
        database.exec('BEGIN IMMEDIATE')
        database.prepare('INSERT INTO persisted_docs VALUES(?,?,?,?,?,?,?)').run('durable', 'session', 1, 'message', 1, 'current', 7)
        database.prepare('INSERT INTO temp.live_docs VALUES(?,?,?,?,?,?,?)').run('live', 'session', 2, 'message', 2, 'current', 4)
        database.exec('UPDATE search_state SET global_generation = 1')
        database.exec('ROLLBACK')
        for table in ('persisted_docs', 'temp.live_docs'):
            assert database.prepare('SELECT count(*) AS count FROM ' + table).get() == {'count': 0}
        assert database.prepare('SELECT global_generation FROM search_state').get() == {'global_generation': 0}
    finally:
        database.close()


def test_failed_query_schema_initialization_closes_unpublished_real_connection(tmp_path, monkeypatch):
    opened = []

    class ObservedDatabase(SqliteDatabase):
        def __init__(self, path):
            super().__init__(path)
            opened.append(self)

    def fail_temporary(database):
        database.exec('invalid SQL')

    monkeypatch.setattr(query_schema, 'SqliteDatabase', ObservedDatabase)
    monkeypatch.setattr(query_schema, '_temporary_schema', fail_temporary)
    path = tmp_path / 'failed.sqlite'
    with pytest.raises(DatabaseError) as raised:
        query_schema.open_search_database(str(path), 'delete')
    assert raised.value.code == 1
    assert len(opened) == 1
    with pytest.raises(RuntimeError, match='closed'):
        opened[0].prepare('SELECT 1')
    path.rename(tmp_path / 'retired.sqlite')
    (tmp_path / 'retired.sqlite').unlink()


@pytest.mark.parametrize('mode', ['off', 'memory', 'wal;DROP TABLE search_state'])
def test_query_schema_refuses_journal_modes_before_file_creation(tmp_path, mode):
    path = tmp_path / 'absent' / 'index.sqlite'
    with pytest.raises(ValueError, match='journal mode'):
        query_schema.open_search_database(str(path), mode)
    assert not path.parent.exists()
