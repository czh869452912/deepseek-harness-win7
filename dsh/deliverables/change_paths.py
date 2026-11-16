"""Native path classification and original code-unit display ordering."""
import asyncio
import os
import tempfile


def toPosix(path):
    return path.replace(os.sep, '/')


def isInside(root, path):
    try:
        relative = os.path.relpath(path, root)
    except ValueError:
        return False
    return relative == '.' or not relative.startswith('..') and not os.path.isabs(relative)


def _canonical_path(path):
    missing, head = [], path
    while True:
        try:
            if not os.path.exists(head):
                raise FileNotFoundError(head)
            return os.path.join(os.path.realpath(head), *missing)
        except OSError:
            parent = os.path.dirname(head)
            if parent == head or os.path.dirname(parent) == parent:
                return path
            missing.insert(0, os.path.basename(head))
            head = parent


async def canonicalPath(path):
    return await asyncio.get_running_loop().run_in_executor(None, _canonical_path, path)


async def temporaryRoots(candidates=None):
    roots = dict()
    for root in candidates if candidates is not None else ['/tmp', tempfile.gettempdir()]:
        roots[root] = None
        roots[await canonicalPath(root)] = None
    return list(roots)


def isTemporaryPath(path, roots):
    return any(isInside(root, path) for root in roots)


def displayPathOf(absolute, cwd, root, home):
    if isInside(cwd, absolute) or isInside(root, absolute):
        return '' if os.path.normcase(absolute) == os.path.normcase(cwd) else toPosix(os.path.relpath(absolute, cwd))
    if home != '' and isInside(home, absolute):
        relative = '' if os.path.normcase(absolute) == os.path.normcase(home) else toPosix(os.path.relpath(absolute, home))
        return '~/'+relative
    return toPosix(absolute)


def durablePathOf(absolute, cwd):
    if not isInside(cwd, absolute):
        return absolute
    return '' if os.path.normcase(absolute) == os.path.normcase(cwd) else toPosix(os.path.relpath(absolute, cwd))


def compareDisplay(a, b):
    left = a['display'].encode('utf-16-be', 'surrogatepass')
    right = b['display'].encode('utf-16-be', 'surrogatepass')
    return -1 if left < right else 1 if left > right else 0
