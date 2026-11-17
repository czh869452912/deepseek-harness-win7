"""Current live Config query status, pagination and projection observations."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
_FILES=None


def cases():
    rows=[dict(input=value) for value in [None,False,3,'input',[],{},dict(limit=2),dict(offset=2,limit=3),dict(offset=1000),dict(offset=1e300),dict(name='with-schema'),dict(name='none'),dict(name='with-schema',offset=1,limit=1)]]
    rows.extend(dict(input=dict(entry=name)) for name in ['group','include','unloaded','disposed','disabled','absent','foreign','schema','failed','same','group:child','no-package'])
    rows.extend(dict(input=dict(entry=value)) for value in ['',None,False,3,{},[],'unknown','\n"中文'])
    for key in ['offset','limit']:
        rows.extend(dict(input={key:value}) for value in [False,True,-1,.5,'1',[],{},0,1,100,101,None])
    rows.extend(dict(input=dict(name=value)) for value in ['',None,False,3,{},[]])
    rows.extend(dict(input=dict(entry=None,offset=value)) for value in [False,-1])
    rows.extend(dict(special=special) for special in ['nan-offset','infinite-offset','nan-limit'])
    rows.append(dict(input=dict(entry='schema'),noLoader=True))
    rows.append(dict(input=dict(entry='schema'),noBase=True))
    rows.append(dict(input=dict(entry='schema'),noPackages=True))
    rows.append(dict(input=dict(entry='schema'),lookupError=True))
    rows.extend(dict(input=dict(entry='schema'),mutation=mutation) for mutation in ['dispose','disable','remove-config','replace-config'])
    return rows


def prepare(output):
    global _FILES
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8')
    _FILES=output/'files'/'profile';manifests=[]
    for name in ['dsh-config-contract-dep','@scope/dsh-config-contract-dep']:
        directory=_FILES/'node_modules'/name;directory.mkdir(parents=True)
        manifest=directory/'package.json';manifest.write_text(json.dumps(dict(name=name,version='1.0.0',exports={'.':'./absent.js'})),encoding='utf-8');manifests.append(manifest)
    meta=output/'package-inputs.json';meta.write_text(json.dumps(dict(base=str(_FILES))),encoding='utf-8')
    return [path,meta,*manifests]


def fixture_entries(ctx, no_base=False):
    from dsh.cordis.schema import Schema as S
    parent=NS(tree=NS(ctx=NS(baseUrl=None if no_base else 'file:///fixture/')))
    schema=S.object({'port':S.number().default(80).description('Listen port.')})
    rows=[]
    for key in ['group','include','unloaded','disposed','disabled','absent','foreign','schema','failed','same','group:child','no-package']:
        name='with-schema' if key in ['schema','same','failed','group:child','no-package'] else key
        config=schema if name=='with-schema' else {'foreign':True} if key=='foreign' else None
        fiber=NS(uid=None if key=='disposed' else 0,runtime=NS(Config=config))
        rows.append(NS(id=key,options=dict(id=key.split(':')[-1],name=name),parent=parent,
            subgroup=NS() if key=='group' else None,subtree=NS() if key=='include' else None,
            fiber=None if key=='unloaded' else fiber,disabled=key=='disabled'))
    return rows


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.schema import Schema
    from dsh.javascript.runtime import JavaScriptRuntime
    from dsh.extensions.inspect_config_current import query_live_config
    rows=[]
    ctx=Context()
    try:
        await ctx.plugin(JavaScriptRuntime)
        for entry in cases():
            entries=fixture_entries(ctx,entry.get('noBase'));calls=[]
            loader=NS(entries=lambda:iter(entries),resolve=lambda key:next(row for row in entries if row.id==key))
            def package_of(name,base):
                calls.append([name,base])
                if entry.get('lookupError'):raise ValueError('package lookup failed')
                return dict(dir='/fixture/packages/'+name) if name!='absent' else None
            query_ctx=NS(get=lambda key: (None if entry.get('noLoader') else loader) if key=='loader'
                else (None if entry.get('noPackages') else NS(packageOf=package_of)) if key=='pluginPackages' else ctx.get(key))
            node=next(row for row in entries if row.id=='schema')
            mutation=entry.get('mutation')
            if mutation=='dispose':node.fiber.uid=None
            if mutation=='disable':node.disabled=True
            if mutation=='remove-config':node.fiber.runtime.Config=None
            if mutation=='replace-config':node.fiber.runtime.Config=Schema.string().required()
            input=entry.get('input')
            if entry.get('special'):input={'limit' if entry['special']=='nan-limit' else 'offset':float('inf') if entry['special']=='infinite-offset' else float('nan')}
            row=dict(case=entry,calls=calls)
            try:row['value']=await query_live_config(query_ctx,input)
            except Exception as error:row['error']=str(error)
            rows.append(row)
        if _FILES is not None:
            from dsh.boot.plugin_packages import PluginPackages
            packages=PluginPackages(ctx)
            bases=[_FILES.as_uri()+'/',(_FILES/'caller.js').as_uri(),_FILES.as_uri(),_FILES.as_uri()+'/?q=1#hash']
            for index,base in enumerate(bases):
                for name in ['dsh-config-contract-dep/private','@scope/dsh-config-contract-dep']:
                    rows.append(dict(packageLookup=dict(base=index,name=name),value=packages.packageOf(name,base)))
        assert not ctx.jsRuntime._workers
    finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_inspect_config.mts',prepare=prepare,
        scope='Live Config query contract against fixed Source: controlled Loader entries for all statuses, exact name/entry lookup, numeric pagination validation, package scope and actual native Schema projection. Actual Loader lifecycle is verified separately.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/extensions/inspect_config_current.py',ROOT/'dsh/boot/config_graph_current.py'])
