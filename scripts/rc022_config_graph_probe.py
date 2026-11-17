"""Live Python Schema and ordered lazy-builder projection observations."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[dict(kind=kind) for kind in ['string','required','default','bad-default','object','shared','recursive','transform','volatile','constant','annotations']]
    rows.extend(dict(kind='lazy',mode=mode) for mode in ['fresh','cached','loose','metadata','cycle','bad','throw','volatile','mutation','replace-meta','shared'])
    rows.extend(dict(kind='pattern',source=source,flags=flags) for source in ['^[a-z]+$','.*a.*','😀','^a\\b','[\\d\\s]+'] for flags in ['', 'u','i'])
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


def make_schema(entry, calls):
    from dsh.cordis.schema import Schema as S
    kind=entry['kind']
    if kind=='string':return S.string()
    if kind=='required':return S.string().required()
    if kind=='default':return S.number().default(3)
    if kind=='bad-default':return S.number().default('bad')
    if kind=='object':return S.object({'token':S.string().required(),'nested':S.object({'flag':S.boolean()})})
    if kind=='shared':
        node=S.string().required();return S.object({'a':node,'b':node})
    if kind=='recursive':
        node=S({'type':'object'});node.dict={'child':node};return node
    if kind=='transform':
        def transform(value):
            calls.append('transform');raise AssertionError('transform must not execute')
        return S.transform(S.dict(S.number(),S.string()),transform)
    if kind=='volatile':return S.array(S.string().volatile())
    if kind=='constant':return S.const({'constructor':3,'a':None,'b':[1,2]})
    if kind=='annotations':return S.string().description({'en':'English','zh':'中文'}).role('secret').default('abc')
    if kind=='pattern':
        node=S.string();node.meta['pattern']=dict(source=entry['source'],flags=entry['flags']);return node
    mode=entry['mode'];shared=S.string();node=S({'type':'lazy'})
    def builder():
        calls.append('builder')
        if mode=='cycle':return node
        if mode=='bad':return 42
        if mode=='throw':raise ValueError('builder failed')
        if mode=='volatile':return S.string().volatile()
        if mode=='mutation':shared.meta['required']=True
        if mode=='replace-meta':shared.meta={'required':True}
        return S.object({'value':shared})
    node.builder=builder
    if mode=='cached':node.inner=S.string()
    if mode=='loose':node.meta['loose']=True
    if mode=='metadata':node.meta['required']=True
    if mode in ('mutation','replace-meta'):return S.object({'before':shared,'lazy':node,'after':shared})
    if mode=='shared':return S.object({'a':node,'b':node})
    return node


async def observe():
    from dsh.cordis import Context
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.boot.config_graph_current import project_native_config
    ctx=Context();rows=[]
    try:
        await ctx.plugin(JavaScriptRuntime)
        for entry in cases():
            calls=[];schema=make_schema(entry,calls);row=dict(case=entry,calls=calls)
            try:row['value']=await project_native_config(ctx,schema,'live')
            except Exception as error:row['error']=str(error)
            rows.append(row)
        assert not ctx.jsRuntime._workers
    finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_config_graph.mts',prepare=prepare,
        scope='Actual Source/Python Schema projection through live lazy-builder RPC, sequential async carrier and shared object updates. Includes mutation/replacement during visits, cache, exceptions and opaque transforms. No live Loader provider promotion yet.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/boot/config_graph_current.py',ROOT/'dsh/boot/config_projection_current.py',*list((ROOT/'dsh/boot/config-projection').iterdir())])
