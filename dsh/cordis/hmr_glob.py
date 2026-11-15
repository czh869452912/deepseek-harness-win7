"""Slash-aware module watcher ignore patterns; matching is case sensitive."""
import re
from functools import lru_cache


_POSIX = dict(alnum='a-zA-Z0-9', alpha='a-zA-Z', ascii='\\x00-\\x7f', blank=' \\t',
              cntrl='\\x00-\\x1f\\x7f', digit='0-9', graph='\\x21-\\x7e', lower='a-z',
              print=r' -~', punct=r'\x21-\x2f\x3a-\x40\x5b\x5d-\x60\x7b-\x7e',
              space='\\t\\r\\n\\v\\f ', upper='A-Z', word='A-Za-z0-9_', xdigit='A-Fa-f0-9')


def _closing(pattern, index, left, right):
    depth = 1
    for position in range(index+1, len(pattern)):
        if pattern[position] == left: depth += 1
        elif pattern[position] == right:
            depth -= 1
            if not depth: return position
    return None


def _alternatives(value, separator):
    parts, start, depth = [], 0, 0
    for index, char in enumerate(value):
        if char in '({': depth += 1
        elif char in ')}': depth -= 1
        elif char == separator and depth == 0:
            parts.append(value[start:index]); start = index+1
    return parts+[value[start:]]


def _translate(pattern):
    if pattern.startswith('./'):
        pattern = pattern[2:]
    result, index, start = '', 0, True
    while index < len(pattern):
        char = pattern[index]
        if char in '@+?*!' and pattern[index+1:index+2] == '(' and _closing(pattern, index+1, '(', ')') is not None:
            end = _closing(pattern, index+1, '(', ')')
            inner = '|'.join(_translate(item) for item in _alternatives(pattern[index+2:end], '|'))
            if char == '!':
                tail = pattern[end+1:]
                suffix = _translate(tail) if any(value in pattern[index+2:end] for value in '*?') and '/' not in tail else ''
                result += (r'(?=[^\n\r\u2028\u2029])' if index == 0 else '')+'(?!(?:'+inner+')'+suffix+('$' if end == len(pattern)-1 else '')+')[^/]*'
            else:
                result += (r'(?=[^\n\r\u2028\u2029])' if index == 0 and char != '@' else '')+'(?:'+inner+')'+({'@':'', '+':'+', '?':'?', '*':'*'}[char])
            index = end+1
        elif char == '*':
            end = index+1
            while end < len(pattern) and pattern[end] == '*':
                end += 1
            globstar = end-index > 1 and start and (end == len(pattern) or pattern[end] == '/')
            if globstar and end < len(pattern):
                result += '(?:/|(?:(?!\\.)[^/]+/)*)'
                index, start = end+1, True
                continue
            result += (r'(?=[^\n\r\u2028\u2029])(?!\.)' if start else '') + ('(?:(?!/\\.).)*' if globstar else '[^/]*')
            index = end
        elif char == '?':
            result += ('(?!\\.)' if start else '') + '[^/]'
            index += 1
        elif char == '[' and ']' in pattern[index+1:]:
            end = pattern.index(']', index+1)
            if pattern[index+1:index+3] == '[:' and pattern[end+1:end+2] == ']': end += 1
            value = pattern[index+1:end]
            value = re.sub(r'\[:([a-z]+):\]', lambda match: _POSIX.get(match.group(1), match.group(0)), value)
            result += (r'(?=[^\n\r\u2028\u2029])' if start else '')+'['+value+']'
            index = end+1
        elif char == '{' and _closing(pattern, index, '{', '}') is not None:
            end = _closing(pattern, index, '{', '}')
            value = pattern[index+1:end]
            ranges = value.split('..')
            if len(ranges) > 1 and all(len(item) == 1 for item in ranges):
                result += '['+'-'.join(sorted(ranges))+']'
            elif '..' in value:
                result += re.escape(value)
            else:
                result += '(?:'+'|'.join(_translate(item) for item in _alternatives(value, ','))+')'
            index = end+1
        elif char == '(' and _closing(pattern, index, '(', ')') is not None:
            end = _closing(pattern, index, '(', ')')
            result += '(?:'+'|'.join(_translate(item) for item in _alternatives(pattern[index+1:end], '|'))+')'
            index = end+1
        elif char == '\\' and index+1 < len(pattern):
            result += re.escape(pattern[index+1])
            index += 2
        elif char == '/' and pattern[index+1:] == '**':
            result += '(?:/(?!\\.)(?:(?!/\\.).)*)?'
            index = len(pattern)
        else:
            if char == '.' and start and pattern[index+1:index+2] == '*':
                result += '(?!\\.(?:/|$))'
            result += re.escape(char)
            index += 1
        start = char == '/'
    return result


@lru_cache(maxsize=256)
def _compile(pattern):
    if not pattern:
        raise ValueError('Expected pattern to be a non-empty string')
    suffix = '/?' if pattern.endswith(('*', '?', ']')) and not pattern.endswith(')') else ''
    return re.compile('^(?:'+_translate(pattern)+')'+suffix+'$')


def matches(path, patterns):
    if not path:
        return False
    for pattern in patterns:
        if path == pattern:
            return True
        count = 0
        while pattern[count:count+1] == '!' and pattern[count+1:count+2] != '(': count += 1
        negative = bool(count % 2)
        if negative and any(char in path for char in '\n\r\u2028\u2029'):
            continue
        if bool(_compile(pattern[count:]).fullmatch(path)) != negative:
            return True
    return False
