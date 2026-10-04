MAX_SAFE = 9007199254740991
PREFIX = 'malformed source_event_seqs storage value: '


def append_varint(output, value):
    while value >= 128:
        output.append((value & 127) | 128)
        value >>= 7
    output.append(value)


def encode_source_event_seqs(values):
    if not values:
        return b''
    deltas = bytearray([0])
    previous = 0
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > MAX_SAFE or value != int(value):
            raise TypeError('sourceEventSeqs must contain non-negative safe integers')
        current = int(value)
        encoded = current if index == 0 else (current - previous) * 2 if current >= previous else (previous - current) * 2 - 1
        append_varint(deltas, encoded)
        previous = current
    if not all(index == 0 or value > values[index - 1] for index, value in enumerate(values)):
        return bytes(deltas)
    runs = bytearray([1])
    start = end = int(values[0])
    for value in values[1:]:
        value = int(value)
        if value == end + 1:
            end = value
            continue
        append_varint(runs, start)
        append_varint(runs, end - start + 1)
        start = end = value
    append_varint(runs, start)
    append_varint(runs, end - start + 1)
    return bytes(runs if len(runs) < len(deltas) else deltas)


def read_varint(data, offset, limit):
    value = shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            if shift > 0 and byte & 127 == 0:
                raise ValueError(PREFIX + 'non-canonical varint')
            if value > limit:
                raise ValueError(PREFIX + 'varint is out of range')
            return value, offset
        shift += 7
        if shift > 56:
            raise ValueError(PREFIX + 'varint is out of range')
    raise ValueError(PREFIX + 'truncated varint')


def decode_source_event_seqs(data, max_entries):
    if not data:
        return []
    if len(data) == 1:
        raise ValueError(PREFIX + 'truncated tagged payload')
    if data[0] not in (0, 1):
        raise ValueError(PREFIX + 'unknown encoding tag')
    values = []
    offset = 1
    previous = 0
    previous_end = -1
    while offset < len(data):
        if data[0] == 0:
            first = not values
            decoded, offset = read_varint(data, offset, MAX_SAFE if first else MAX_SAFE * 2)
            delta = decoded if first else decoded // 2 if decoded % 2 == 0 else -(decoded + 1) // 2
            value = delta if first else previous + delta
            if value < 0 or value > MAX_SAFE:
                raise ValueError(PREFIX + 'decoded seq is out of range')
            values.append(value)
            previous = value
        else:
            start, offset = read_varint(data, offset, MAX_SAFE)
            length, offset = read_varint(data, offset, MAX_SAFE)
            if length < 1:
                raise ValueError(PREFIX + 'run count must be positive')
            end = float(start) + length - 1
            if start <= previous_end or end < -MAX_SAFE or end > MAX_SAFE or end != int(end):
                raise ValueError(PREFIX + 'runs must ascend within safe integers')
            if length > max_entries - len(values):
                raise ValueError(PREFIX + 'run exceeds its event sequence')
            values.extend(start + index for index in range(length))
            previous_end = end
    return values
