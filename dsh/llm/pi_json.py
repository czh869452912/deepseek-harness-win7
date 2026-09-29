"""Repair and incremental JSON parsing matching the pinned pi-ai tool stream."""
import json
import math
import re


def _reject_constant(value):
    raise ValueError('Non-JSON numeric constant: ' + value)


def loads(value):
    return json.loads(value, parse_constant=_reject_constant)


def dumps(value):
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            return None
        if isinstance(item, dict):
            return {key: finite(value) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [finite(value) for value in item]
        return item
    return json.dumps(finite(value), ensure_ascii=False, separators=(',', ':'))


def repair_json(raw):
    output, quoted, index = [], False, 0
    while index < len(raw):
        char = raw[index]
        index += 1
        if not quoted:
            output.append(char)
            quoted = char == '"'
        elif char == '"':
            output.append(char)
            quoted = False
        elif char == '\\':
            following = raw[index:index + 1]
            if following == 'u' and re.fullmatch('[0-9a-fA-F]{4}', raw[index + 1:index + 5]):
                output.append('\\' + raw[index:index + 5])
                index += 5
            elif following and following in '"\\/bfnrtu':
                output.append('\\' + following)
                index += 1
            else:
                output.append('\\\\')
        elif ord(char) < 32:
            output.append(json.dumps(char)[1:-1])
        else:
            output.append(char)
    return ''.join(output)


class _Partial:
    def __init__(self, raw):
        self.raw, self.index = raw.strip(), 0

    def peek(self):
        return self.raw[self.index:self.index + 1]

    def blank(self):
        while self.peek() and self.peek() in ' \n\r\t':
            self.index += 1

    def string(self):
        start, escaped = self.index, False
        self.index += 1
        while self.peek() and (self.peek() != '"' or escaped):
            escaped = not escaped if self.peek() == '\\' else False
            self.index += 1
        if self.peek() == '"':
            self.index += 1
            return loads(self.raw[start:self.index - int(escaped)])
        try:
            return loads(self.raw[start:self.index - int(escaped)] + '"')
        except ValueError:
            end = self.raw.rfind('\\')
            return loads(self.raw[start:max(start, end)] + '"')

    def value(self):
        self.blank()
        char = self.peek()
        if not char:
            raise ValueError('incomplete')
        if char == '"':
            return self.string()
        if char in '{[':
            self.index += 1
            object_mode = char == '{'
            result = {} if object_mode else []
            try:
                self.blank()
                while self.peek() != ('}' if object_mode else ']'):
                    self.blank()
                    if object_mode:
                        if not self.peek():
                            return result
                        key = self.string()
                        self.blank()
                        self.index += 1
                        result[key] = self.value()
                    else:
                        result.append(self.value())
                    self.blank()
                    if self.peek() == ',':
                        self.index += 1
            except (ValueError, IndexError):
                return result
            self.index += 1
            return result
        tail = self.raw[self.index:]
        for spelling, value in [('null', None), ('true', True), ('false', False),
                                ('Infinity', float('inf')), ('-Infinity', float('-inf')), ('NaN', float('nan'))]:
            if tail.startswith(spelling) or (spelling.startswith(tail) and (spelling != '-Infinity' or len(tail) > 1)):
                self.index += len(spelling)
                return value
        start = self.index
        if start == 0:
            self.index = len(self.raw)
        else:
            while self.peek() and self.peek() not in ',]}':
                self.index += 1
        raw = self.raw[start:self.index]
        try:
            return loads(raw)
        except ValueError:
            end = raw.rfind('e')
            if end < 0:
                raise
            return loads(raw[:end])


def parse_streaming_json(raw):
    if not raw or not raw.strip():
        return {}
    repaired = repair_json(raw)
    for candidate in (raw, repaired):
        try:
            return loads(candidate)
        except ValueError:
            pass
    for candidate in (raw, repaired):
        try:
            value = _Partial(candidate).value()
            return {} if value is None else value
        except (ValueError, IndexError, RecursionError):
            pass
    return {}
