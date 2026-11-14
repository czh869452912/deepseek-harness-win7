"""Classify the evaluated dependency graph before partial module replacement."""
import asyncio


def excluded(url):
    return url.startswith('node:') or '/node_modules/' in url


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
