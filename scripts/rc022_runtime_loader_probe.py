"""Compare real Source ESM imports with routed Python plugin imports."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_packages_probe import fixture
OUTPUT=None
MODES=['active','sibling','outside-profile','nested','local-empty','declared-local','linked-peer','linked-local','linked-deep','linked-unlisted','installation-overlap']


def prepare(output):
    global OUTPUT
    OUTPUT=output
    cases=[]
    from dsh.boot.plugin_packages import _parent
    for mode in MODES:
        row=dict(mode=mode)
        for host in ('source','native'):
            directory=output/'files'/host/mode;table,parent=fixture(directory,mode)
            for manifest in directory.rglob('package.json'):
                value=json.loads(manifest.read_text(encoding='utf-8'))
                entry='index.mjs' if host=='source' else 'index.py'
                value['main']=entry;value['exports']={'.':'./'+entry}
                manifest.write_text(json.dumps(value),encoding='utf-8')
                text='export const value='+json.dumps(value['name'])+'\n' if host=='source' else 'value='+repr(value['name'])+'\ndef apply(ctx, config): pass\n'
                (manifest.parent/entry).write_text(text,encoding='utf-8')
            importer=Path(_parent(parent));importer.parent.mkdir(parents=True,exist_ok=True)
            if host=='source':importer.write_text('export function load(name) { return import(name) }\n',encoding='utf-8')
            row[host]=dict(table=table,parent=parent)
        cases.append(row)
    path=output/'input.json';path.write_text(json.dumps(cases),encoding='utf-8');return [path]


async def native():
    from dsh.boot import PluginPackages
    from dsh.cordis import Context
    from dsh.cordis.loader import Loader
    from dsh.boot.plugin_packages import _parent
    result=[]
    for case in json.loads((OUTPUT/'input.json').read_text(encoding='utf-8')):
        data=case['native'];ctx=Context();ctx.baseUrl=Path(_parent(data['parent'])).parent.as_uri()+'/'
        loader=Loader(ctx);service=PluginPackages(ctx,dict(resolution=data['table']))
        try:
            for name in ('core','private','absent'):
                try:value=loader.import_plugin(name).value;error=False
                except Exception:value=None;error=True
                metadata=service.packageOf(name,data['parent'])
                result.append(dict(mode=case['mode'],name=name,value=value,error=error,metadata=None if metadata is None else metadata['name']))
        finally:await ctx.fiber.dispose()
    return result


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_runtime_loader.mts','Real ESM/Python package root imports and metadata ownership under published profile routes; not subpath/self-reference/worker acceptance.',
        [Path(__file__).resolve(),ROOT/'dsh/cordis/loader.py',ROOT/'dsh/boot/plugin_packages.py'],prepare,node_args=('--expose-internals',))
