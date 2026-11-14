"""Pair actual upstream dependency acceptance over deterministic graph inputs."""
import asyncio
import json
from pathlib import Path
import random
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
CASES = []


def cases():
    result = [
        dict(graph={}, stashed=[], externals=[]),
        dict(graph={'changed': ['leaf'], 'leaf': []}, stashed=['changed'], externals=[]),
        dict(graph={'changed': ['cycle'], 'cycle': ['changed']}, stashed=['changed'], externals=[]),
        dict(graph={'changed': ['left', 'right'], 'left': ['right'], 'right': ['left']}, stashed=['changed'], externals=[]),
        dict(graph={'changed': ['external', 'node:fs', '/node_modules/a.js'], 'external': ['changed']}, stashed=['changed'], externals=['external']),
        dict(graph={'changed': ['first', 'second'], 'first': ['second', 'changed'], 'second': ['changed']}, stashed=['changed'], externals=[]),
    ]
    rng = random.Random(20261115)
    for unused in range(600):
        names = ['file:'+str(index) for index in range(rng.randrange(1, 13))]+['node:fs', '/node_modules/package.js']
        graph = {name:rng.sample(names, rng.randrange(min(6, len(names))+1)) for name in names}
        result.append(dict(graph=graph, stashed=rng.sample(names, rng.randrange(min(4, len(names))+1)),
                           externals=rng.sample(names, rng.randrange(min(4, len(names))+1))))
    return result


def prepare(output):
    global CASES
    CASES = cases()
    path = output/'input.json'
    path.write_text(json.dumps(CASES), encoding='utf-8')
    return [path]


async def observe(inputs):
    from dsh.cordis.hmr import ConfigWatcherService
    result = []
    for row in inputs:
        async def linked(url):
            await asyncio.sleep(0)
            return row['graph'].get(url, [])
        owner = SimpleNamespace(_stashed=dict.fromkeys(row['stashed']), externals=dict.fromkeys(row['externals']), getLinked=linked)
        await ConfigWatcherService.analyze_changes(owner)
        result.append(dict(accepted=list(owner.accepted), declined=list(owner.declined)))
    return result


async def native():
    return await observe(CASES)


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_hmr_changes.mts', 'Actual analyzeChanges dependency acceptance, discovery order, cycles, duplicate paths, excluded builtins/dependencies and external overlap; 6 explicit plus 600 deterministic graph cases.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr_changes.py', ROOT/'dsh/cordis/hmr.py', ROOT/'.goose/out/rc022-prep-20261114-01/source/packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
