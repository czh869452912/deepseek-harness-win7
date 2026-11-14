"""Strict npm range semantics used by profile compatibility (includePrerelease).

The comparator expansion follows the pinned node-semver range implementation;
this module needs no Node runtime or additional Portable dependency.
"""
import re
from functools import total_ordering

_NUM = r'(?:0|[1-9][0-9]*)'
_PRE_ID = r'(?:[0-9]*[A-Za-z-][0-9A-Za-z-]*|'+_NUM+r')'
_PRE = r'(?P<pre>'+_PRE_ID+r'(?:\.'+_PRE_ID+r')*)'
_BUILD = r'(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)'
_FULL = re.compile(r'v?(?P<major>'+_NUM+r')\.(?P<minor>'+_NUM+r')\.(?P<patch>'+_NUM+r')(?:-'+_PRE+r')?(?:\+'+_BUILD+r')?')
_PART = r'(?:'+_NUM+r'|[xX*])'
_XRANGE = re.compile(r'[v=\s]*(?P<major>'+_PART+r')(?:\.(?P<minor>'+_PART+r')(?:\.(?P<patch>'+_PART+r')(?:-'+_PRE+r')?(?:\+'+_BUILD+r')?)?)?')
_MAX = 9007199254740991


@total_ordering
class Version:
    def __init__(self, core, pre=None, build=None):
        self.core, self.pre, self.build = tuple(core), pre, build
        if any(value > _MAX for value in self.core):
            raise ValueError('Invalid semantic version component')

    def __eq__(self, other):
        return self.core == other.core and self.pre == other.pre

    def __lt__(self, other):
        if self.core != other.core:
            return self.core < other.core
        if self.pre is None or other.pre is None:
            return self.pre is not None and other.pre is None
        left, right = self.pre.split('.'), other.pre.split('.')
        for a, b in zip(left, right):
            if a == b:
                continue
            an, bn = a.isdigit(), b.isdigit()
            if an and bn:
                return int(a) < int(b)
            if an != bn:
                return an
            return a < b
        return len(left) < len(right)

    def canonical(self):
        return '.'.join(str(n) for n in self.core) + ('-'+self.pre if self.pre is not None else '') + ('+'+self.build if self.build is not None else '')


def parse(value):
    if not isinstance(value, str) or len(value) > 256:
        raise ValueError('Invalid semantic version')
    match = _FULL.fullmatch(value.strip())
    if match is None:
        raise ValueError('Invalid semantic version')
    return Version([int(match[n]) for n in ('major', 'minor', 'patch')], match['pre'], match['build'])


def is_exact_version(value):
    try:
        return parse(value).canonical() == value
    except ValueError:
        return False


def _partial(value):
    match = _XRANGE.fullmatch(value)
    if match is None:
        raise ValueError('Invalid semantic version range')
    parts = [match[n] for n in ('major', 'minor', 'patch')]
    values = [None if n is None or n in ('x', 'X', '*') else int(n) for n in parts]
    if any(n is None and any(p is not None for p in values[i+1:]) for i, n in enumerate(values)):
        raise ValueError('Invalid wildcard order')
    if any(n is not None and n > _MAX for n in values):
        raise ValueError('Invalid semantic version component')
    return values, match['pre']


def _bound(core, pre='0'):
    return Version(core, pre)


def _token(value):
    match = re.fullmatch(r'(~>?|\^|>=|<=|>|<|=)?(.*)', value)
    op, text = match.groups()
    op = op or ''
    parts, pre = _partial(text)
    major, minor, patch = parts
    if major is None:
        return [('<', _bound((0, 0, 0)))] if op in ('>', '<') else []
    core = (major, minor or 0, patch or 0)
    if op in ('~', '~>', '^'):
        low = _bound(core, pre if pre is not None else ('0' if None in parts else None))
        if minor is None or (op == '^' and major != 0):
            high = (major+1, 0, 0)
        elif op in ('~', '~>') or patch is None or minor != 0:
            high = (major, minor+1, 0)
        else:
            high = (major, minor, patch+1)
        return [('>=', low), ('<', _bound(high))]
    if None not in parts:
        # Numeric x-range tokens are left to the strict comparator parser by
        # node-semver. A malformed prefix such as v= must not be normalized.
        return [(op or '=', parse(text))]
    high = (major+1, 0, 0) if minor is None else (major, minor+1, 0)
    if op in ('', '='):
        return [('>=', _bound(core)), ('<', _bound(high))]
    if op == '>':
        return [('>=', _bound(high))]
    if op == '<=':
        return [('<', _bound(high))]
    return [(op, _bound(core))]


def _hyphen(left, right):
    start, start_pre = _partial(left)
    end, end_pre = _partial(right)
    result = []
    if start[0] is not None:
        result.append(('>=', _bound([n or 0 for n in start], start_pre or '0')))
    a, b, c = end
    if a is not None:
        if b is None:
            result.append(('<', _bound((a+1, 0, 0))))
        elif c is None:
            result.append(('<', _bound((a, b+1, 0))))
        elif end_pre is not None:
            result.append(('<=', _bound((a, b, c), end_pre)))
        else:
            result.append(('<', _bound((a, b, c+1))))
    return result


def _branch(value):
    value = value.strip()
    if not value:
        return []
    hyphen = re.fullmatch(r'(.+?)\s+-\s+(.+)', value)
    if hyphen:
        return _hyphen(*hyphen.groups())
    value = re.sub(r'(~>?|\^|[<>]=?|=)\s+', r'\1', value)
    result = []
    for token in value.split():
        result.extend(_token(token))
    return result


def satisfies(version, requirement):
    """Return false for malformed/empty ranges; prereleases always participate."""
    if not isinstance(requirement, str) or not requirement.strip():
        return False
    try:
        candidate = parse(version)
        branches = [_branch(value) for value in requirement.split('||')]
        def matches(op, bound):
            if op == '=':
                return candidate == bound
            if op == '>':
                return candidate > bound
            if op == '>=':
                return candidate >= bound
            if op == '<':
                return candidate < bound
            return candidate <= bound
        return any(all(matches(op, bound) for op, bound in branch) for branch in branches)
    except (ValueError, TypeError, OverflowError):
        return False
