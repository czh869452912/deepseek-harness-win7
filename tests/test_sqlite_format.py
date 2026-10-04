from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from dsh.session.sqlite_codec import pack_chunk_runs, MAX_PACKED_DATA_BYTES
from dsh.session.sqlite_compression import bind_record, decode_data, decode_row, scan_rows
from dsh.session.sqlite_database import SqliteDatabase
from dsh.session.sqlite_source_seqs import decode_source_event_seqs
from dsh.session import zstd


def chunk(sequence):
    return dict(type='assistant/chunk', seq=sequence, time=sequence * 2,
                data=dict(turn=1, step=1, chunk=dict(type='text-delta', index=0, text='界' * 100)))


def test_schema_owned_packed_rows_survive_actual_strict_sqlite_and_detached_reads():
    events = [chunk(sequence) for sequence in range(2051)]
    records = pack_chunk_runs(events)
    assert len(records) == 3
    database = SqliteDatabase(':memory:')
    try:
        database.exec('CREATE TABLE records (seq INTEGER PRIMARY KEY, type TEXT NOT NULL, time INTEGER NOT NULL, '
                      'data ANY NOT NULL, source_event_seqs BLOB, surface_op TEXT, is_packed INTEGER NOT NULL) STRICT')
        statement = database.prepare('INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?)')
        for record in records:
            bound = bind_record(record)
            statement.run(*[bound[name] for name in ('seq', 'type', 'time', 'data', 'source_event_seqs', 'surface_op', 'is_packed')])
        detached = database.prepare('SELECT * FROM records ORDER BY seq').all()
        assert all(isinstance(row['data'], bytes) for row in detached)
    finally:
        database.close()
    assert scan_rows(detached) == dict(preserved=events)
    assert [event for row in detached for event in decode_row(row)] == events


@pytest.mark.parametrize('committed', [False, True])
def test_physical_corruption_is_repairable_only_without_a_later_valid_turn_end(committed):
    start = bind_record(dict(type='turn/start', seq=0, time=0, data=dict(turn=1)))
    invalid = dict(start, seq=1, data=b'not zstd')
    rows = [start, invalid]
    if committed:
        rows.append(bind_record(dict(type='turn/end', seq=2, time=2, data=dict(turn=1))))
        with pytest.raises(ValueError, match='invalid committed physical row at seq 1'):
            scan_rows(rows)
    else:
        assert scan_rows(rows) == dict(preserved=[dict(type='turn/start', seq=0, time=0, data=dict(turn=1))], tornFrom=1)


@pytest.mark.parametrize('size', [65535, 65536, 65537, 100000, 131072, 200000, 1048576])
def test_private_decoder_preserves_complete_output_across_buffer_boundaries(size):
    data = b'x' * size
    encoded = zstd.compress(data)
    assert zstd.decompress(encoded) == data
    assert zstd.decompress(encoded, size) == data
    with pytest.raises(zstd.ZstdError) as captured:
        zstd.decompress(encoded, size - 1)
    assert captured.value.code == 'ERR_BUFFER_TOO_LARGE'


def test_packed_output_is_bounded_during_decompression_before_json_parse():
    encoded = zstd.compress(b' ' * (MAX_PACKED_DATA_BYTES + 1))
    row = dict(type='text-chunks', seq=0, time=0, data=encoded, source_event_seqs=None, surface_op=None, is_packed=1)
    with pytest.raises(zstd.ZstdError) as captured:
        decode_row(row)
    assert captured.value.code == 'ERR_BUFFER_TOO_LARGE'


def test_fatal_utf8_and_bom_match_original_data_column_semantics():
    assert decode_data(zstd.compress(b'\xef\xbb\xbfnull')) == 'null'
    with pytest.raises(zstd.ZstdError) as captured:
        decode_data(zstd.compress(b'\xff\xfe'))
    assert captured.value.code == 'ERR_ENCODING_INVALID_ENCODED_DATA'


def test_surface_fields_validate_before_malformed_scalar_data():
    row = dict(type='custom/event', seq=0, time=0, data='invalid JSON', source_event_seqs=b'\x02\x00',
               surface_op='{bad', is_packed=0)
    with pytest.raises(ValueError, match='unknown encoding tag'):
        decode_row(row)


def test_scalar_json_numbers_use_ieee754_and_refuse_non_json_constants():
    row = dict(type='custom/event', seq=0, time=0, data='9007199254740993', source_event_seqs=None, surface_op=None, is_packed=0)
    assert decode_row(row)[0]['data'] == 9007199254740992
    with pytest.raises(ValueError, match='Invalid JSON numeric constant'):
        decode_row(dict(row, data='NaN'))


def test_provenance_run_expansion_is_bounded_before_allocation():
    with pytest.raises(ValueError, match='run exceeds its event sequence'):
        decode_source_event_seqs(bytes.fromhex('0100ffffffffffffff0f'), 5)


@pytest.mark.parametrize('name', ['dsh_zstd.dll', 'zstd-dictionary.bin', 'zstd.json', 'build-provenance.json',
                                 'ZSTD-LICENSE', 'LLVM-LICENSE.txt', 'MinGW-COPYING'])
def test_changed_private_zstd_assets_fail_closed(tmp_path, name):
    shutil.copytree(zstd.ROOT, tmp_path / 'assets')
    path = tmp_path / 'assets' / name
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(RuntimeError, match='Pinned Zstandard'):
        zstd.verify_zstd_files(path.parent)


def test_zstd_builder_exposes_explicit_staging_inputs():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, str(root / 'scripts/build_zstd.py'), '--help'], capture_output=True, text=True)
    assert result.returncode == 0
    assert all(flag in result.stdout for flag in ('--source', '--compiler', '--output', '--stage-output', '--stage-only'))
