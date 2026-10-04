import math

from dsh.cordis.json_text import stringify_json
from dsh.session.sqlite_json import parse_json

MIN_PACKED_ROW_MEMBERS = 3
MAX_PACKED_ROW_MEMBERS = 1024
MAX_PACKED_DATA_BYTES = 1048576
MAX_SAFE_INTEGER = 9007199254740991
TAGS = ('text-chunks', 'reasoning-chunks', 'tool-call-chunks')


def is_number(value):
    return type(value) in (int, float)


def safe_integer(value):
    return is_number(value) and -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER and math.isfinite(value) and int(value) == value


def exact_keys(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def classify(event):
    if not exact_keys(event, ['type', 'seq', 'time', 'data']) or event['type'] != 'assistant/chunk':
        return None
    if not safe_integer(event['seq']) or event['seq'] < 0 or not safe_integer(event['time']):
        return None
    data = event['data']
    if not exact_keys(data, ['turn', 'step', 'chunk']) or not is_number(data['turn']) or not is_number(data['step']):
        return None
    chunk = data['chunk']
    if not isinstance(chunk, dict) or not is_number(chunk.get('index')):
        return None
    kind = chunk.get('type')
    if kind in ('text-delta', 'reasoning-delta'):
        return kind if exact_keys(chunk, ['type', 'index', 'text']) and isinstance(chunk['text'], str) else None
    if kind == 'tool-call-delta':
        keys = ['type', 'index', 'id', 'argumentsDelta']
        valid_keys = exact_keys(chunk, keys) or (exact_keys(chunk, keys + ['name']) and isinstance(chunk['name'], str))
        return kind if valid_keys and isinstance(chunk['id'], str) and isinstance(chunk['argumentsDelta'], str) else None
    return None


def continues(previous, current, kind):
    if current['seq'] != previous['seq'] + 1 or not safe_integer(current['time'] - previous['time']):
        return False
    if any(current['data'][key] != previous['data'][key] for key in ('turn', 'step')):
        return False
    left, right = previous['data']['chunk'], current['data']['chunk']
    if left['index'] != right['index']:
        return False
    return kind != 'tool-call-delta' or (left['id'] == right['id'] and ('name' in left) == ('name' in right) and left.get('name') == right.get('name'))


def build_row(kind, run):
    first = run[0]
    data = dict(turn=first['data']['turn'], step=first['data']['step'], index=first['data']['chunk']['index'],
                dt=[event['time'] - run[index]['time'] for index, event in enumerate(run[1:])])
    if kind == 'tool-call-delta':
        data['id'] = first['data']['chunk']['id']
        if 'name' in first['data']['chunk']:
            data['name'] = first['data']['chunk']['name']
        data['args'] = [event['data']['chunk']['argumentsDelta'] for event in run]
        tag = 'tool-call-chunks'
    else:
        data['texts'] = [event['data']['chunk']['text'] for event in run]
        tag = 'text-chunks' if kind == 'text-delta' else 'reasoning-chunks'
    return dict(type=tag, seq0=first['seq'], time0=first['time'], data=data)


def data_bytes(row):
    return len(stringify_json(row['data']).encode('utf-8'))


def emit_run(output, kind, run):
    offset = 0
    while len(run) - offset >= MIN_PACKED_ROW_MEMBERS:
        low, high = MIN_PACKED_ROW_MEMBERS, min(len(run) - offset, MAX_PACKED_ROW_MEMBERS)
        largest = build_row(kind, run[offset:offset + high])
        if data_bytes(largest) <= MAX_PACKED_DATA_BYTES:
            output.append(largest)
            offset += high
            continue
        high -= 1
        accepted, row = 0, None
        while low <= high:
            middle = (low + high) // 2
            candidate = build_row(kind, run[offset:offset + middle])
            if data_bytes(candidate) <= MAX_PACKED_DATA_BYTES:
                accepted, row, low = middle, candidate, middle + 1
            else:
                high = middle - 1
        if accepted == 0:
            output.append(run[offset])
            offset += 1
        else:
            output.append(row)
            offset += accepted
    output.extend(run[offset:])


def pack_chunk_runs(events):
    output, run, kind = [], [], None
    def flush():
        nonlocal run, kind
        if kind is None:
            output.extend(run)
        else:
            emit_run(output, kind, run)
        run, kind = [], None
    for event in events:
        next_kind = classify(event)
        if next_kind is None:
            flush()
            output.append(event)
        elif run and next_kind == kind and continues(run[-1], event, next_kind):
            run.append(event)
        else:
            flush()
            kind, run = next_kind, [event]
    flush()
    return output


def malformed(tag, reason):
    raise ValueError('malformed ' + tag + ' storage row: ' + reason)


def validate_data(tag, data, payload_key, serialized_bytes):
    if any(not is_number(data.get(key)) for key in ('turn', 'step', 'index')):
        malformed(tag, 'turn/step/index must be numbers')
    payload = data.get(payload_key)
    if (not isinstance(payload, list) or not MIN_PACKED_ROW_MEMBERS <= len(payload) <= MAX_PACKED_ROW_MEMBERS
            or any(not isinstance(value, str) for value in payload)):
        malformed(tag, payload_key + ' must contain 3..1024 strings')
    gaps = data.get('dt')
    if not isinstance(gaps, list) or any(not safe_integer(gap) for gap in gaps):
        malformed(tag, 'dt must be an array of safe integers')
    if len(gaps) != len(payload) - 1:
        malformed(tag, 'dt length must match the member count')
    length = len(stringify_json(data).encode('utf-8')) if serialized_bytes is None else serialized_bytes
    if length > MAX_PACKED_DATA_BYTES:
        malformed(tag, 'data exceeds 1048576 UTF-8 bytes')
    return payload


def validate_row(value, tag, serialized_bytes=None):
    if not exact_keys(value, ['type', 'seq0', 'time0', 'data']):
        malformed(tag, 'invalid envelope fields')
    if not safe_integer(value['seq0']) or value['seq0'] < 0:
        malformed(tag, 'seq0 must be non-negative')
    if not safe_integer(value['time0']):
        malformed(tag, 'time0 must be a safe integer')
    data = value['data']
    if not isinstance(data, (dict, list)):
        malformed(tag, 'data must be an object')
    if tag == 'tool-call-chunks':
        keys = ['turn', 'step', 'index', 'id', 'dt', 'args']
        with_name = exact_keys(data, keys + ['name'])
        if not with_name and not exact_keys(data, keys):
            malformed(tag, 'invalid tool-call data fields')
        if not isinstance(data['id'], str) or (with_name and not isinstance(data['name'], str)):
            malformed(tag, 'id and optional name must be strings')
        payload = validate_data(tag, data, 'args', serialized_bytes)
    else:
        if not exact_keys(data, ['turn', 'step', 'index', 'dt', 'texts']):
            malformed(tag, 'invalid text data fields')
        payload = validate_data(tag, data, 'texts', serialized_bytes)
    if not safe_integer(float(value['seq0']) + len(payload) - 1):
        malformed(tag, 'member seqs exceed safe integers')
    current_time = value['time0']
    for gap in data['dt']:
        current_time += gap
        if not safe_integer(current_time):
            malformed(tag, 'member times exceed safe integers')
    return value


def expand_row(row):
    data, events, current_time = row['data'], [], row['time0']
    tool = row['type'] == 'tool-call-chunks'
    for index, payload in enumerate(data['args' if tool else 'texts']):
        if index:
            current_time += data['dt'][index - 1]
        if tool:
            chunk = dict(type='tool-call-delta', index=data['index'], id=data['id'])
            if 'name' in data:
                chunk['name'] = data['name']
            chunk['argumentsDelta'] = payload
        else:
            chunk = dict(type='text-delta' if row['type'] == 'text-chunks' else 'reasoning-delta', index=data['index'], text=payload)
        events.append(dict(type='assistant/chunk', seq=float(row['seq0']) + index, time=current_time,
                           data=dict(turn=data['turn'], step=data['step'], chunk=chunk)))
    return events


def decode_storage_record(value):
    if not isinstance(value, dict) or value.get('type') not in TAGS:
        return [value]
    return expand_row(validate_row(value, value['type']))


def decode_serialized_chunk_row(tag, seq0, time0, serialized_data):
    normalized = serialized_data.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='replace')
    length = len(normalized.encode('utf-8'))
    if length > MAX_PACKED_DATA_BYTES:
        malformed(tag, 'data exceeds 1048576 UTF-8 bytes')
    data = parse_json(serialized_data)
    return expand_row(validate_row(dict(type=tag, seq0=seq0, time0=time0, data=data), tag, length))
