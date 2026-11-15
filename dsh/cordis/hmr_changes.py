"""Classify the evaluated dependency graph before partial module replacement."""
import asyncio
import os
import sysconfig
from functools import lru_cache

from dsh.cordis.hmr_paths import file_path


_HOST_ROOTS = tuple(os.path.normcase(os.path.realpath(path))+os.sep for path in {
    os.path.dirname(os.path.dirname(__file__)),
    sysconfig.get_path('stdlib'), sysconfig.get_path('platstdlib'),
    sysconfig.get_path('purelib'), sysconfig.get_path('platlib'),
} if path)


@lru_cache(maxsize=4096)
def excluded(url):
    if url.startswith('node:') or '/node_modules/' in url:
        return True
    if not url.startswith('file:/'):
        return False
    # Python's SDK/stdlib and interpreter-installed packages correspond to
    # Node builtins/framework packages, rather than user watch-root modules.
    # Evicting them would also remove the running loader's own dependencies.
    path = os.path.normcase(os.path.realpath(file_path(url)))
    return any(path.startswith(root) for root in _HOST_ROOTS)


async def analyze_changes(hmr):
    pending = []
    accepted = dict.fromkeys(hmr._stashed)
    declined = dict.fromkeys(hmr.externals)

    async def collect(url):
        children = await hmr.getLinked(url)
        for child in children:
            if child in accepted or child in declined or excluded(child):
                continue
            pending.append(child)
    await asyncio.gather(*(collect(url) for url in hmr._stashed))
    while pending:
        index, updated = 0, False
        while index < len(pending):
            url = pending[index]
            children = await hmr.getLinked(url)
            is_declined, is_accepted = True, False
            for child in children:
                if child in declined or excluded(child):
                    continue
                if child in accepted:
                    is_accepted = True
                    break
                is_declined = False
                if child not in pending:
                    updated = True
                    pending.append(child)
            if is_accepted or is_declined:
                updated = True
                pending.pop(index)
                if is_accepted:
                    accepted[url] = None
                else:
                    declined[url] = None
            else:
                index += 1
        if not updated:
            break
    declined.update(dict.fromkeys(pending))
    hmr.accepted, hmr.declined = accepted, declined
