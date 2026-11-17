"""Compare current on-demand browser chunks over fixed shared entry artifacts."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
NAME='@fixture/assets'


def manifest(target='client.js'):
    return dict(name=NAME,version='1.0.0',type='module',exports={'.':'./host.js','./client':'./'+target},dsh=dict(client=dict(platform='web')))


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';directory=WORKSPACE/'node_modules'/NAME;directory.mkdir(parents=True)
    for name,body in [('host.js','export default () => {}'),('client.js','module.exports={entry:1};'),('next.js','module.exports={entry:200};'),
        ('client.node.js','throw Error("not browser")'),('client.node.helper.js','throw Error("not browser either")')]:
        (directory/name).write_text(body,encoding='utf-8')
    (directory/'package.json').write_text(json.dumps(manifest()),encoding='utf-8')
    import hashlib
    (output/'fixture-inputs.json').write_text(json.dumps({str(path.relative_to(WORKSPACE)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in WORKSPACE.rglob('*') if path.is_file()},indent=2),encoding='utf-8')
    path=output/'inputs.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE))),encoding='utf-8')
    return [path,output/'fixture-inputs.json']


async def setup(workspace):
    from dsh.cordis import Context
    from dsh.host.client_modules.current import CurrentClientModuleRegistry
    directory=workspace/'node_modules'/NAME
    (directory/'package.json').write_text(json.dumps(manifest()),encoding='utf-8')
    ctx=Context();entry=NS(options=dict(name=NAME),fiber=NS(),disabled=False,parent=NS(tree=NS(ctx=NS(baseUrl=workspace.as_uri()+'/'))))
    ctx.provide('loader',NS(entries=lambda:iter([entry])))
    try:return ctx,CurrentClientModuleRegistry(ctx),entry
    except BaseException:await ctx.fiber.dispose();raise


async def observe(workspace=None):
    workspace=workspace or WORKSPACE;directory=workspace/'node_modules'/NAME;chunk=directory/'client.terminal.js'
    # Only ephemeral chunk/map data changes; the entry artifacts used for stat
    # revisions remain identical for both implementations throughout the pair.
    if chunk.exists():chunk.unlink()
    ctx,registry,entry=await setup(workspace);rows=[]
    try:
        revision=registry.graph()['entries'][0]['rev']
        url=lambda file,rev=revision:'/plugins/'+NAME+'/'+file+'?rev='+rev
        async def request(stage,target,method='GET'):
            result=await registry.fetchBundle(dict(url='http://x'+target,method=method))
            rows.append(dict(stage=stage,status=result['status'],headers=result['headers'],body=(result['body'] or b'').decode('utf-8')))
        await request('missing',url(chunk.name))
        chunk.write_text('module.exports={generation:1};',encoding='utf-8')
        await request('head',url(chunk.name),'HEAD');await request('script',url(chunk.name));await request('map',url(chunk.name+'.map'))
        await request('stale',url(chunk.name,'stale'));await request('extra-query',url(chunk.name)+'&extra=1')
        for name in ['client.node.js','client.node.helper.js','client.node.js.map','client.node.helper.js.map','client.js','other.js','client..js']:
            await request('blocked-'+name,url(name))
        chunk.write_text('module.exports={generation:2};',encoding='utf-8')
        await request('cached',url(chunk.name))
        # A metadata-only recomposition must retain the existing chunk body.
        changed=manifest();changed['dsh']['client']['immediately']=True
        (directory/'package.json').write_text(json.dumps(changed),encoding='utf-8')
        registry.dirty[NAME]=None;registry.reconcile(activation=True)
        await request('cached-after-compose',url(chunk.name))
        (directory/'package.json').write_text(json.dumps(manifest('next.js')),encoding='utf-8')
        registry.dirty[NAME]=None;registry.reconcile(activation=True)
        next_rev=registry.graph()['entries'][0]['rev']
        await request('prior-rejected',url(chunk.name));await request('next-generation',url(chunk.name,next_rev))
        entry.disabled=True;registry.dirty[NAME]=None;registry.reconcile(activation=True)
        await request('removed',url(chunk.name,next_rev))
        return rows
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_client_chunks.mts',prepare=prepare,
        scope='Actual Source/Native on-demand chunk and map bytes/headers, scoped assets package names, strict current revision/name rejection, HEAD, immutable caching across metadata recomposition, changed export generation and removal.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/host/client_modules/current.py',ROOT/'dsh/host/client_modules/resources_current.py'])
