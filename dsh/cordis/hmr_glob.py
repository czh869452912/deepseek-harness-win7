"""Slash-aware module watcher ignore patterns; matching is case sensitive."""
import re
from functools import lru_cache


def _translate(pattern):
    if pattern.startswith('./'):
        pattern = pattern[2:]
    result, index, start = '', 0, True
    while index < len(pattern):
        char = pattern[index]
        if char == '*':
            end = index+1
            while end < len(pattern) and pattern[end] == '*':
                end += 1
            globstar = end-index > 1 and start and (end == len(pattern) or pattern[end] == '/')
            if globstar and end < len(pattern):
                result += '(?:(?!\\.)[^/]+/)*'
                index, start = end+1, True
                continue
            result += ('(?=[^/])(?!\\.)' if start else '') + ('(?:(?!/\\.).)*' if globstar else '[^/]*')
            index = end
        elif char == '?':
            result += ('(?!\\.)' if start else '') + '[^/]'
            index += 1
        elif char == '[' and ']' in pattern[index+1:]:
            end = pattern.index(']', index+1)
            value = pattern[index+1:end]
            result += ('(?!\\.)' if start else '')+'['+value+']'
            index = end+1
        elif char == '{' and '}' in pattern[index+1:]:
            end = pattern.index('}', index+1)
            result += '(?:'+'|'.join(_translate(item) for item in pattern[index+1:end].split(','))+')'
            index = end+1
        elif char == '\\' and index+1 < len(pattern):
            result += re.escape(pattern[index+1])
            index += 2
        elif char == '/' and pattern[index+1:] == '**':
            result += '(?:/(?!\\.)(?:(?!/\\.).)*)?'
            index = len(pattern)
        else:
            result += re.escape(char)
            index += 1
        start = char == '/'
    return result


@lru_cache(maxsize=256)
def _compile(pattern):
    if not pattern:
        raise ValueError('Expected pattern to be a non-empty string')
    return re.compile('^(?:'+_translate(pattern)+')/?$')


def matches(path, patterns):
    if not path:
        return False
    for pattern in patterns:
        negative = pattern.startswith('!') and not pattern.startswith('!(')
        if bool(_compile(pattern[1:] if negative else pattern).match(path)) != negative:
            return True
    return False
