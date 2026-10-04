import math
import re
import struct

from dsh.session.session_query import SessionQueryError
from dsh.session.text import WHITESPACE, trim_text


MAX_SAFE_INTEGER = 9007199254740991
ISO_TIMESTAMP = re.compile(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|([+-])(\d{2}):(\d{2}))$', re.ASCII)


def invalid_range(name, detail):
    return SessionQueryError('session ' + name + ' range ' + detail, 'SESSION_QUERY_INVALID_FILTER')


def assert_non_negative_safe_integer(name, value):
    if type(value) not in (int, float) or not 0 <= value <= MAX_SAFE_INTEGER or not math.isfinite(value) or int(value) != value:
        raise SessionQueryError(name + ' must be a non-negative safe integer', 'SESSION_QUERY_INVALID_FILTER')


def assert_non_empty_array(name, values):
    if len(values) == 0:
        raise SessionQueryError(name + ' must contain at least one value when supplied', 'SESSION_QUERY_INVALID_FILTER')


def normalize_query(value):
    query = re.sub(WHITESPACE + '+', ' ', trim_text(value))
    if not query:
        raise SessionQueryError('session-search query must contain non-whitespace text', 'SESSION_QUERY_INVALID_QUERY')
    if '\0' in query:
        raise SessionQueryError('session-search query must not contain NUL', 'SESSION_QUERY_INVALID_QUERY')
    return query


def sequence_range(lower=None, upper=None):
    result = {}
    if lower is not None:
        assert_non_negative_safe_integer('sequence lower bound', lower)
        result['from'] = lower
    if upper is not None:
        assert_non_negative_safe_integer('sequence upper bound', upper)
        result['to'] = upper
    if lower is not None and upper is not None and lower > upper:
        raise invalid_range('sequence', 'from must be less than or equal to to')
    return result


def days_in_month(year, month):
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31


def days_from_civil(year, month, day):
    adjusted_year = year - (month <= 2)
    era = adjusted_year // 400
    year_of_era = adjusted_year - era * 400
    shifted_month = month + (-3 if month > 2 else 9)
    day_of_year = (153 * shifted_month + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def parse_iso_timestamp(name, value):
    match = ISO_TIMESTAMP.fullmatch(value)
    if match is None:
        raise invalid_range(name, 'must be an ISO 8601 timestamp with Z or a numeric offset')
    year, month, day, hour, minute = [int(match.group(index)) for index in range(1, 6)]
    second, offset_hour, offset_minute = [int(match.group(index) or '0') for index in (6, 10, 11)]
    if (not 1 <= month <= 12 or not 1 <= day <= days_in_month(year, month)
            or hour > 23 or minute > 59 or second > 59 or offset_hour > 23 or offset_minute > 59):
        raise invalid_range(name, 'must be a valid ISO 8601 timestamp')
    fraction = match.group(7) or ''
    timestamp = ((days_from_civil(year, month, day) * 24 + hour) * 60 + minute) * 60000
    timestamp += second * 1000 + int(fraction[:3].ljust(3, '0'))
    offset = (offset_hour * 60 + offset_minute) * 60000
    timestamp -= offset if match.group(9) == '+' else -offset
    return timestamp, fraction[3:].rstrip('0')


def adjacent_float(value, upward):
    if value == 0:
        return 5e-324 if upward else -5e-324
    bits = struct.unpack('>Q', struct.pack('>d', value))[0]
    bits += 1 if (value > 0) == upward else -1
    return struct.unpack('>d', struct.pack('>Q', bits))[0]


def timestamp_range(name, lower=None, upper=None):
    if lower is None and upper is None:
        return None
    lower_timestamp = parse_iso_timestamp(name + '_from', lower) if lower is not None else None
    upper_timestamp = parse_iso_timestamp(name + '_to', upper) if upper is not None else None
    if lower_timestamp is not None and upper_timestamp is not None:
        remainder_width = max(len(lower_timestamp[1]), len(upper_timestamp[1]))
        lower_exact = lower_timestamp[0], lower_timestamp[1].ljust(remainder_width, '0')
        upper_exact = upper_timestamp[0], upper_timestamp[1].ljust(remainder_width, '0')
        if lower_exact > upper_exact:
            raise invalid_range(name, 'from must be less than or equal to to')
    result = {}
    if lower_timestamp is not None:
        result['from'] = adjacent_float(lower_timestamp[0], True) if lower_timestamp[1] else lower_timestamp[0]
    if upper_timestamp is not None:
        result['to'] = adjacent_float(upper_timestamp[0] + 1, False) if upper_timestamp[1] else upper_timestamp[0]
    return result


def build_session_filters(args):
    filters = []
    if 'session_ids' in args:
        assert_non_empty_array('session_ids', args['session_ids'])
        filters.append(dict(kind='id', values=list(args['session_ids'])))
    created = timestamp_range('created_at', args.get('created_at_from'), args.get('created_at_to'))
    if created is not None:
        filters.append(dict(kind='created-at', **created))
    if 'availability' in args:
        assert_non_empty_array('availability', args['availability'])
        filters.append(dict(kind='availability', values=list(args['availability'])))
    return filters


def materialize_parent_ids(values):
    if values is None:
        return None
    assert_non_empty_array('parent_session_ids', values)
    return list(dict.fromkeys(values))


def build_event_filters(lower=None, upper=None, time_lower=None, time_upper=None, event_types=None, surfaces=None):
    filters = []
    sequence = sequence_range(lower, upper)
    if sequence:
        filters.append(dict(kind='seq', **sequence))
    timestamp = timestamp_range('time', time_lower, time_upper)
    if timestamp is not None:
        filters.append(dict(kind='time', **timestamp))
    for name, kind, values in [('event_types', 'type', event_types), ('surfaces', 'surface', surfaces)]:
        if values is not None:
            assert_non_empty_array(name, values)
            filters.append(dict(kind=kind, values=list(values)))
    return filters
