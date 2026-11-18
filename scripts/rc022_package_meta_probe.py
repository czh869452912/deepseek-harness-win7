"""Pair localized display values and diagnostic presence through real exports."""
import base64
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_resolution_probe import package
OUTPUT = None
DEFAULT_EXPORTS = {'.':'./index.mjs','./locale/*.json':'./locale/*.json'}
CASES = []


def add(**case): CASES.append(case)
def dictionary(**meta): return dict(meta=meta)


add(requests=['localized','absent','fs','node:fs','cordis:group','./entry.py','file:///plugins/search.js','C:\\plugins\\search.js','//server/share/plugin.js'])
add(locales={'en':{},'zh':dict(other={'title':'ignored'})})
add(locales={'en':dictionary(title='Team',description='Work together'),'zh':dictionary(title='团队'),'pt-BR':dictionary(description='Trabalhar juntos')})
add(locales={'en':dictionary(title='%title%',description='Plugin %name%')})
add(locales={'en':dictionary(description='English'),'zh':dictionary(title='标题')})
add(locales={'en':{},'zh':dictionary(description='介绍')})
add(exports={'./package.json':'./package.json'},description='Package introduction')
add(exports=None,description='Plain bundle')
add(exports=dict(DEFAULT_EXPORTS,**{'./package.json':'./package.json'}),description='Package introduction',locales={'en':dictionary(title='Title'),'zh':dictionary(description='介绍')})
add(exports={'./search/locale/*.json':'./locale/*.json','./search/package.json':'./broken.json'},locales={'en':dictionary(title='Search')},files={'broken.json':'{'},requests=['localized/search'])
add(exports={'./package.json':'./display.json'},files={'display.json':'{}'})
add(exports={'./package.json':'./display.json'},files={'display.json':json.dumps(dict(name=False,description=None))})
add(exports={'./package.json':'./display.json'},files={'display.json':'{'})
for value in (None,[],False,1,'text'): add(locales={'en':dict(meta=value)})
for field in ('title','description'):
    for value in (None,False,1,{},'', '  ', '\ufeff', '\x1c'): add(locales={'en':dict(meta={field:value})})
for value in (None,[],'text'): add(locales={'en':value})
add(locales={'en':dictionary(title='Title')},files={'locale/zh.json':'{'})
add(files={'locale/en.json':'{"meta":{"title":NaN}}'})
add(locales={'en':dictionary(title='Title'),'not_a_language':dictionary(title='Bad')})
add(exports={'./locale/en.json':'./locale/en.json'},locales={'en':dictionary(title='English'),'zh':dictionary(title='中文')})
add(exports=dict(DEFAULT_EXPORTS,**{'./locale/zh.json':'./separate/zh.json'}),locales={'en':dictionary(title='English'),'zh':dictionary(title='中文')},files={'separate/zh.json':json.dumps(dictionary(title='Mapped'))})
add(exports={'./locale/*.json':'../outside/*.json'})
add(exports={'./search/locale/*.json':'./search/*.json','./review/locale/*.json':'./review/*.json'},files={'search/en.json':json.dumps(dictionary(title='Search')),'review/en.json':json.dumps(dictionary(title='Review'))},requests=['localized/search','localized/review','localized/private'])
add(exports={'./locale/*.json':{'import':'./esm/*.json','require':'./cjs/*.json'}},files={'esm/en.json':json.dumps(dictionary(title='ESM')),'cjs/en.json':json.dumps(dictionary(title='CJS'))})
for extension in ('svg','png','jpg','jpeg','webp','SVG','gif','html',''):
    filename='icon'+('.'+extension if extension else '')
    add(exports={'./package.json':'./package.json','./icon':'./'+filename},binary={filename:5})
for icon in (None,False,1,'',' ','/tmp/icon.svg','C:/icons/icon.svg','https://example.test/icon.svg','../outside.svg'):
    add(exports={'./package.json':'./package.json','./icon':'./fallback.svg'},icon=icon,files={'fallback.svg':'fallback'})
for icon in ('missing.svg','directory.svg','oversized.svg','unsupported.gif'):
    add(exports={'./package.json':'./package.json','./icon':'./fallback.svg'},icon=icon,files={'fallback.svg':'fallback','unsupported.gif':'gif'},directories=['directory.svg'],binary={'oversized.svg':256*1024+1})
add(exports={'./package.json':'./package.json','./icon':'../invalid.svg'},icon='./legacy.svg',files={'legacy.svg':'legacy'})
add(exports={'./package.json':'./display/manifest.json','./icon':'./fallback.svg'},files={'display/manifest.json':json.dumps(dict(icon='./logo.svg')),'display/logo.svg':'remapped','fallback.svg':'fallback'})
add(exports={'./package.json':'./display/manifest.json','./icon':'./fallback.svg'},files={'display/manifest.json':json.dumps(dict(icon='../outside.svg')),'outside.svg':'outside','fallback.svg':'fallback'})
add(exports={'./icon':'./root.svg','./search/icon':'./search.svg'},files={'root.svg':'root','search.svg':'search'},requests=['localized','localized/search','localized/review'])
for target in (False,1,'','/tmp/icon.svg','../icon.svg','https://example.test/icon.svg'):
    add(exports=dict(DEFAULT_EXPORTS,**{'./icon':target}),locales={'en':dictionary(title='Plugin')})
for size in (256*1024,256*1024+1):
    add(exports={'./package.json':'./package.json','./icon':'./icon.png'},binary={'icon.png':size})
add(exports={'./icon':'./missing.svg'})
add(exports={'./icon':'./directory.svg'},directories=['directory.svg'])
for location in ('inside','outside'):
    add(exports={'./icon':'./art/icon.svg'},link=location)


def prepare(output):
    global OUTPUT
    OUTPUT = output; rows=[]
    for index, case in enumerate(CASES):
        row=dict(index=index,fixture=case)
        for host in ('source','native'):
            directory=output/'files'/host/str(index); active=directory/'profiles/active'
            anchor=package(directory/'installation','installation'); package(active,'caller')
            library=anchor.parent/'node_modules/localized'
            fields={key:case[key] for key in ('description','icon') if key in case}
            package(library,'localized',exports=case.get('exports',DEFAULT_EXPORTS),**fields)
            (library/'index.mjs').write_text('throw new Error("must not execute")',encoding='utf-8')
            files=dict(case.get('files',{}))
            files.update({'locale/'+language+'.json':json.dumps(value,ensure_ascii=False) for language,value in case.get('locales',{}).items()})
            for name,text in files.items():
                path=library/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
            for name,size in case.get('binary',{}).items(): (library/name).write_bytes(bytes(i%256 for i in range(size)))
            for name in case.get('directories',[]): (library/name).mkdir()
            if 'link' in case:
                from dsh.boot.profile import create_symlink
                target=(library if case['link']=='inside' else directory)/'art-target'
                package(target,'nested');(target/'icon.svg').write_text(case['link'],encoding='utf-8')
                create_symlink(str(target),str(library/'art'))
            table=dict(profilesDir=str(directory/'profiles'),profileDir=str(active),entries=[dict(name='localized',packageDir=str(library),declarer=str(anchor),version='1.0.0',scope='installation')],localPackageNames=[],linkedRoots=[])
            row[host]=dict(table=table,parent=(active/'caller.mjs').as_uri())
        rows.append(row)
    path=output/'input.json';path.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8');return [path]


def normalize(value):
    if value is None:return None
    value=dict(value)
    if 'error' in value:value['error']=True
    if 'icon' in value:
        header,data=value['icon'].split(',',1);data=base64.b64decode(data)
        value['icon']=dict(header=header,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    return value


async def native():
    from dsh.boot import PluginPackages
    from dsh.cordis import Context
    result=[];raw=[]
    for row in json.loads((OUTPUT/'input.json').read_text(encoding='utf-8')):
        data=row['native'];ctx=Context();service=PluginPackages(ctx,dict(resolution=data['table']))
        try:
            for request in row['fixture'].get('requests',['localized']):
                value=service.metaOf(request,data['parent'])
                result.append(dict(case=row['index'],request=request,value=normalize(value)))
                raw.append(dict(case=row['index'],request=request,error=None if value is None else value.get('error')))
        finally:await ctx.fiber.dispose()
    (OUTPUT/'native-diagnostics.json').write_text(json.dumps(raw,ensure_ascii=False),encoding='utf-8');return result


if __name__=='__main__':
    probe.native=native;source=ROOT/'reference'
    probe.main('rc022_package_meta.mjs','Actual exported locale/manifest/icon values, icon byte hashes and diagnostic presence; raw wording retained separately.',
        [Path(__file__).resolve(),ROOT/'dsh/boot/package_meta.py',ROOT/'dsh/boot/plugin_packages.py',ROOT/'dsh/boot/package_resolution.py',source/'packages/boot/app-boot/lib/index.js',source/'packages/boot/app-boot/src/package-meta.ts'],prepare,node_args=('--expose-internals',),plain_node=True)
