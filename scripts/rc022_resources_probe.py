"""Pair fixed Node resource decisions without executing package entries."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_resolution_probe import package
OUTPUT=None
SOURCE=ROOT/'reference'
EXPORTS=[
 './root.json',None,{},[],42,
 {'.':'./root.json','./feature':'./feature.json'},
 {'node':'./node.json','import':'./import.json','default':'./default.json'},
 {'import':'./import.json','node':'./node.json'},
 {'.':{'browser':'./browser.json','default':'./default.json'}},
 {'.':{'browser':'./browser.json'}},
 {'.':['not-relative','./root.json']},
 {'.':['./missing.json','./root.json']},
 {'.':[None,'./root.json']},
 {'.':[False,None]},
 {'.':'./root.json','node':'./node.json'},
 {'.':{'0':'./root.json','default':'./default.json'}},
 {'./*':'./wild/*.json','./feature/*':'./specific/*.json','./feature/exact':'./exact.json'},
 {'./*':'./wild/*.json','./feature/*':None},
 {'.':'../outside.json'}, {'.':'./node_modules/x.json'},
 {'.':'./%2e%2e/outside.json'}, {'.':'./folder/'},
 {'.':'./root.json?query#fragment'}, {'./*':'./wild/*.json'},
]
IMPORTS=[{'#exact':'./root.json'}, {'#exact':'lib/feature'}, {'#exact':{'node':'lib/feature','import':'./root.json'}},
 {'#exact':['../invalid','./root.json']}, {'#exact':None}, {'#*':'./wild/*.json','#feature/*':'lib/*'},
 {'#exact':'../outside.json'}, {'#exact':'https://example.com'}, {'#exact':'./node_modules/x.json'}]


def prepare(output):
    global OUTPUT
    OUTPUT=output
    cases=[]
    for index,value in enumerate(EXPORTS):
        cases.append(dict(mode='exports',value=value,requests=['lib','lib/feature','lib/feature/exact','lib/feature/item','lib/other','lib/feature/../outside','lib/a%2fb']))
    for value in IMPORTS:
        cases.append(dict(mode='imports',value=value,requests=['#exact','#feature/item','#other','#','#/bad','#feature/']))
    cases.extend([dict(mode='self',value={'.':'./root.json','./feature':'./feature.json'},requests=['lib','lib/feature']),
        dict(mode='legacy',value=None,requests=['lib','lib/feature.json','lib/folder','lib/missing.json']),
        dict(mode='relative',value=None,requests=['./root.json','./folder/','./missing.json','fs'])])
    path=output/'input.json';path.write_text(json.dumps(cases),encoding='utf-8');return [path]


def fixture(directory,case):
    active=directory/'profiles/active';anchor=package(directory/'installation','installation')
    library=anchor.parent/'node_modules/lib';package(library,'lib')
    fields=dict(main='./root.json') if case['mode']=='legacy' else dict(exports=case['value'] if case['mode'] in ('exports','self') else {'.':'./root.json','./feature':'./feature.json','./item':'./item.json'})
    package(library,'lib',**fields)
    package(active,'caller',**(dict(imports=case['value']) if case['mode']=='imports' else {}))
    if case['mode']=='self':package(active,'lib',exports=case['value'])
    for root in (active,library):
        for name in ('root','feature','node','import','default','browser','exact','item'):
            (root/(name+'.json')).write_text('{}',encoding='utf-8')
        for sub in ('wild/feature','wild/other','wild/a%2fb','wild/exact','specific/item','specific/exact'):
            file=root/(sub+'.json');file.parent.mkdir(parents=True,exist_ok=True);file.write_text('{}',encoding='utf-8')
        (root/'folder').mkdir()
    table=dict(profilesDir=str(directory/'profiles'),profileDir=str(active),entries=[dict(name='lib',packageDir=str(library),declarer=str(anchor),version='1.0.0',scope='installation')],localPackageNames=[],linkedRoots=[])
    return table,(active/'caller.mjs').as_uri()


async def native():
    from dsh.boot import PluginPackages
    from dsh.cordis import Context
    result=[];raw=[]
    for index,case in enumerate(json.loads((OUTPUT/'input.json').read_text(encoding='utf-8'))):
        directory=OUTPUT/'files/native'/str(index);table,parent=fixture(directory,case)
        ctx=Context();service=PluginPackages(ctx,dict(resolution=table))
        try:
            for request in case['requests']:
                try:value=service.resolveResource(request,parent).replace(str(directory),'$ROOT');code=None;error=None
                except Exception as failure:value=None;code=getattr(failure,'code',type(failure).__name__);error=str(failure)
                result.append(dict(index=index,request=request,path=value,code=code));raw.append(dict(index=index,request=request,error=error))
        finally:await ctx.fiber.dispose()
    (OUTPUT/'native-diagnostics.json').write_text(json.dumps(raw),encoding='utf-8');return result


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_resources.mjs','Actual package ESM resource exports/imports, conditions, patterns and file checks without entry execution.',
        [Path(__file__).resolve(),ROOT/'dsh/boot/package_resolution.py',ROOT/'dsh/boot/plugin_packages.py',SOURCE/'packages/boot/app-boot/lib/index.js',SOURCE/'vendor/cordis/lib/index.js',SOURCE/'packages/boot/app-boot/src/package-meta.ts',SOURCE/'packages/boot/app-boot/src/profile-resolution/resolver.ts'],prepare,node_args=('--expose-internals',),plain_node=True)
