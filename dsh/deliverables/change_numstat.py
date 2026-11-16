"""NUL-separated Git numstat records, including rename records."""
import math
import re

from dsh.cordis.utils import _V8_WHITESPACE_OR_LINE_TERMINATOR


def _number(text):
    value = text.strip(''.join(chr(code) for code in _V8_WHITESPACE_OR_LINE_TERMINATOR))
    if not value:
        return 0
    if re.fullmatch(r'0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+', value):
        try:
            return float(int(value, 0))
        except OverflowError:
            return math.inf
    if not re.fullmatch(r'[+-]?(?:Infinity|(?:(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))', value, re.ASCII):
        return math.nan
    return float(value)


def parseNumstat(output):
    queue = output.split('\0')
    if queue[-1] != '':
        raise ValueError('numstat output is not NUL-terminated')
    queue.pop()
    entries = []
    index = 0
    while index < len(queue):
        record = queue[index]
        index += 1
        first = record.find('\t')
        second = -1 if first < 0 else record.find('\t', first+1)
        if second < 0:
            raise ValueError('malformed numstat record: '+record)
        added, deleted, path = record[:first], record[first+1:second], record[second+1:]
        entry = dict(path=path)
        if path == '':
            if index+1 >= len(queue):
                raise ValueError('malformed numstat rename record')
            entry['oldPath'], entry['path'] = queue[index], queue[index+1]
            index += 2
        binary = added == '-'
        entry.update(added=0 if binary else _number(added), deleted=0 if binary else _number(deleted), binary=binary)
        entries.append(entry)
    return entries
