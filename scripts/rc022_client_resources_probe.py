"""Pair current lazy HTTP resources with the fixed Source provider."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
NAMES=['fixture-lazy','fixture-neighbor']


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files'
    for name in NAMES:
        directory=WORKSPACE/'node_modules'/name;directory.mkdir(parents=True)
        (directory/'host.js').write_text('export default () => {}',encoding='utf-8')
        (directory/'client.js').write_text('module.exports = { name: "%s" };\n//# sourceMappingURL=client.js.map' % name,encoding='utf-8')
        (directory/'package.json').write_text(json.dumps(dict(name=name,version='1.0.0',type='module',
            exports={'.':'./host.js','./client':'./client.js'},dsh=dict(client=dict(platform='web')))),encoding='utf-8')
    path=output/'inputs.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE))),encoding='utf-8')
    # Frozen entry/stat fixtures are hashed before either consumer runs.
    import hashlib
    (output/'fixture-inputs.json').write_text(json.dumps({str(path.relative_to(WORKSPACE)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in WORKSPACE.rglob('*') if path.is_file()},indent=2),encoding='utf-8')
    return [path,output/'fixture-inputs.json']


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.host.client_modules.current import CurrentClientModuleRegistry
    workspace=workspace or WORKSPACE;ctx=Context();rows=[]
    entries=[NS(options=dict(name=name),fiber=NS(),disabled=False,parent=NS(tree=NS(ctx=NS(baseUrl=workspace.as_uri()+'/')))) for name in NAMES]
    ctx.provide('loader',NS(entries=lambda:iter(entries)))
    directory=workspace/'node_modules'/NAMES[0];map_path=directory/'client.js.map'
    def write_map(value):map_path.write_text(value,encoding='utf-8')
    write_map('{')
    try:
        registry=CurrentClientModuleRegistry(ctx);reads=[];original=registry.current_source_map
        # Lazy producers invoke the bound reader held at composition, so install
        # the counting wrapper before the next fresh composition.
        def read(path):reads.append(Path(path).parent.name);return original(path)
        registry.current_source_map=read;registry._responses={};registry.compose()
        batch=registry.graph()['batches'][0]['url'];single=registry.graph()['entries'][0]['url']
        map_url=lambda url:url.replace('/client.js','/client.js.map')
        async def request(stage,url,method='GET'):
            result=await registry.fetchBundle(dict(url='http://x/'+url.lstrip('/'),method=method))
            rows.append(dict(stage=stage,status=result['status'],headers=result['headers'],body=(result['body'] or b'').decode('utf-8'),reads=list(reads)))
        await request('script-head',batch,'HEAD');await request('script-first',batch)
        await request('map-head',map_url(batch),'HEAD')
        write_map(json.dumps(dict(version=3,names=[],sources=['src/first.ts'],mappings='AAAA')))
        await request('map-first',map_url(batch))
        write_map(json.dumps(dict(version=3,names=[],sources=['src/second.ts'],mappings='AAAA')))
        await request('map-cached',map_url(batch));await request('script-cached',batch)
        await request('single-map',map_url(single))
        # Recompose an unrelated row without changing any entry artifact bytes.
        entries[1].disabled=True;registry.dirty[NAMES[1]]=None;registry.reconcile(activation=True)
        await request('single-map-after-compose',map_url(single));await request('prior-batch',batch)
        await request('prior-batch-map',map_url(batch))
        await request('unknown','plugins/events');await request('post',batch,'POST')
        # A malformed map is only observed by its first GET, and produces the
        # same generated identity map as the original Source implementation.
        registry._responses={};registry.compose();write_map('{')
        await request('malformed-map',map_url(single))
        return rows
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_client_resources.mts',prepare=prepare,
        scope='Actual Source/Native lazy script/map HTTP bytes and headers, HEAD, independent first GET, immutable retention across graph recomposition, one prior batch, malformed-map fallback and unknown/method rejection.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/host/client_modules/current.py',ROOT/'dsh/host/client_modules/resources_current.py'])
