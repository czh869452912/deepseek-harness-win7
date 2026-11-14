"""Pair ordered replacement plans, cycles and Loader-owned fiber ancestry."""
import json
import os
from pathlib import Path
import random
import sys
from types import SimpleNamespace as NS
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None


def cases():
    result = []
    for mode in ('managed', 'unmanaged', 'child', 'unaffected-parent', 'stale-wrapper', 'unlisted', 'host', 'empty', 'overlap', 'cycle'):
        result.append(dict(mode=mode, stale=[0, 1] if mode == 'overlap' else [0],
                           graph=[[0, 1], [1, 2], [2, 0]] if mode == 'cycle' else [[0, 1]],
                           host=[1] if mode == 'host' else [], locations=[1, 0], fibers=[mode, 'managed']))
    randomizer = random.Random(2203)
    for index in range(350):
        result.append(dict(mode='random-%d'%index, stale=randomizer.sample(range(6), randomizer.randint(0, 6)),
                           graph=[[child, parent] for child in range(6) for parent in range(6) if randomizer.random() < .13],
                           host=[node for node in range(6) if randomizer.random() < .15],
                           locations=[randomizer.randrange(6) for unused in range(4)],
                           fibers=[randomizer.choice(['managed', 'unmanaged', 'child', 'unaffected-parent', 'stale-wrapper', 'unlisted', 'empty']) for unused in range(4)]))
    return result


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


def observe(directory, inputs):
    from dsh.cordis.hmr_plan import plan_replacement
    (directory/'package/nested').mkdir(parents=True)
    (directory/'package/package.json').write_text('{}', encoding='utf-8')
    (directory/'package/nested/package.json').write_text('{}', encoding='utf-8')
    urls = [(directory/'package/nested'/('%s.py'%index)).as_uri() for index in range(6)]
    result = []
    for row in inputs:
        root = NS(uid=0)
        plugins = [object() for unused in row['locations']]
        plugin_ids = {id(plugin):index for index,plugin in enumerate(plugins)}
        entries, runtimes, fiber_ids = [], {}, {}
        for index, (plugin, mode) in enumerate(zip(plugins, row['fibers'])):
            parent = NS(uid=100+index, parent=NS(fiber=root), entry=None)
            current = NS(uid=1+index, parent=NS(fiber=parent if mode in ('child', 'unaffected-parent') else root), entry=None)
            entry = NS(fiber=NS(ctx=NS(fiber=parent if mode in ('child', 'unaffected-parent') else current)))
            current.entry = entry
            parent.entry = entry
            if mode == 'stale-wrapper':
                entry.fiber.ctx.fiber = root
            if mode not in ('unmanaged', 'unlisted'):
                entries.append(entry)
            running = [] if mode == 'empty' else ([parent, current] if mode == 'child' else [current])
            for offset, fiber in enumerate(running):
                fiber_ids[id(fiber)] = '%d:%d'%(index, offset)
            runtimes[id(plugin)] = NS(fibers=running)
        ctx = NS(loader=NS(entries=lambda: entries), registry=NS(get=lambda plugin: runtimes[id(plugin)]))
        importers = {}
        for child, parent in row['graph']:
            values = importers.setdefault(urls[child], [])
            if urls[parent] not in values:
                values.append(urls[parent])
        plan = plan_replacement(ctx, [urls[index] for index in row['stale']], [str(directory/'package')+os.sep], importers,
                                {urls[index] for index in row['host']},
                                lambda url: [plugins[index] for index, location in enumerate(row['locations']) if urls[location] == url])
        result.append(dict(mode=row['mode'], pending=[dict(node=urls.index(item['url']), reason=item['reason']) for item in plan['pending']],
                           evicted=[urls.index(url) for url in plan['evicted']],
                           manifests=[Path(path).relative_to(directory).as_posix() for path in plan['manifests']],
                           plugins=[plugin_ids[id(plugin)] for plugin in plan['plugins']], fibers=[fiber_ids[id(fiber)] for fiber in plan['fibers']]))
    return result


async def native():
    return observe(OUTPUT/'files/native', json.loads((OUTPUT/'input.json').read_text(encoding='utf-8')))


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'.goose/out/rc022-prep-20261114-01/source'
    probe.main('rc022_hmr_plan.mts', 'Read-only ordered plans against unchanged Hmr.planReplacement with controlled module graph, exported plugins, registry fibers and real manifest ancestry. Runtime cache mutation is separate.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr_plan.py', ROOT/'dsh/cordis/hmr_paths.py', source/'packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
