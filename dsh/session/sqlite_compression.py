from dsh.cordis.json_text import stringify_json
from dsh.session.sqlite_codec import TAGS, MAX_PACKED_DATA_BYTES, decode_serialized_chunk_row
from dsh.session.sqlite_source_seqs import encode_source_event_seqs, decode_source_event_seqs
from dsh.session.zstd import compress, decompress, ZstdError
from dsh.session.sqlite_json import parse_json


def encode_data(serialized):
    data = serialized.encode('utf-8')
    compressed = compress(data)
    return compressed if len(compressed) < len(data) else serialized


def decode_data(value, max_output_length=None):
    if isinstance(value, str):
        return value
    decoded = decompress(bytes(value), max_output_length)
    try:
        return decoded.decode('utf-8-sig')
    except UnicodeError:
        raise ZstdError('The encoded data was not valid for encoding utf-8',
                        'ERR_ENCODING_INVALID_ENCODED_DATA', 'TypeError') from None


def bind_record(record):
    if record['type'] in TAGS and 'seq0' in record and 'seq' not in record:
        return dict(seq=record['seq0'], type=record['type'], time=record['time0'],
                    data=encode_data(stringify_json(record['data'])), source_event_seqs=None, surface_op=None, is_packed=1)
    return dict(seq=record['seq'], type=record['type'], time=record['time'], data=encode_data(stringify_json(record['data'])),
                source_event_seqs=encode_source_event_seqs(record['sourceEventSeqs']) if 'sourceEventSeqs' in record else None,
                surface_op=stringify_json(record['surfaceOp']) if 'surfaceOp' in record else None, is_packed=0)


def decode_row(row):
    if row['is_packed'] == 0:
        surface = {}
        if row['source_event_seqs'] is not None:
            surface['sourceEventSeqs'] = decode_source_event_seqs(row['source_event_seqs'], row['seq'])
        if row['surface_op'] is not None:
            surface['surfaceOp'] = parse_json(row['surface_op'])
        return [dict(type=row['type'], seq=row['seq'], time=row['time'], data=parse_json(decode_data(row['data'])), **surface)]
    if row['type'] not in TAGS:
        raise ValueError('malformed %s storage row: packed discriminator requires a chunk tag' % row['type'])
    if row['source_event_seqs'] is not None or row['surface_op'] is not None:
        raise ValueError('malformed %s storage row: packed surface fields must be null' % row['type'])
    return decode_serialized_chunk_row(row['type'], row['seq'], row['time'], decode_data(row['data'], MAX_PACKED_DATA_BYTES))


def scan_rows(rows, base=0):
    last_turn_end_row = -1
    for index in range(len(rows) - 1, -1, -1):
        try:
            if any(event['type'] == 'turn/end' for event in decode_row(rows[index])):
                last_turn_end_row = index
                break
        except Exception:
            pass
    preserved = []
    expected = base
    for row_index, physical in enumerate(rows):
        try:
            logical = decode_row(physical)
        except Exception:
            logical = None
        contiguous = logical is not None
        if logical is not None:
            for event in logical:
                if event['seq'] != expected:
                    contiguous = False
                    break
                expected = float(expected) + 1
        if not contiguous:
            if row_index <= last_turn_end_row:
                raise ValueError('corrupt session log: invalid committed physical row at seq %s' % stringify_json(physical['seq']))
            return dict(preserved=preserved, tornFrom=physical['seq'])
        preserved.extend(logical)
    return dict(preserved=preserved)
