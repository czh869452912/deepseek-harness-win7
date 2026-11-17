"""Pair export-owned package asset routes and immutable cache headers."""
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None
NAME='@fixture/assets'
CASES=[('svg','icon.svg'),('png','photo.png'),('webp','nested/a%20b.webp'),('special',"whale%282x%29%21%27.png"),
    ('large','large.png'),('head','icon.svg','HEAD'),('not-modified','icon.svg','GET','"icon.svg"'),
    ('wrong-etag','icon.svg','GET','"photo.png"'),('weak-etag','icon.svg','GET','W/"icon.svg"'),
    ('post','icon.svg','POST'),('private','private/hidden.png'),('missing','missing.png'),('directory','folder.png'),
    ('unsupported','notes.txt'),('empty',''),('escape','../../secret.png'),('encoded-escape','%2e%2e/%2e%2e/secret.png'),
    ('encoded-slashes','..%2f..%2fsecret.png'),('bad-percent','photo%zz.png'),('bad-utf8','%ff.png'),
    ('literal-percent','100%25.png'),('fragment','a%23b.png')]


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files'
    for name,export in [(NAME,True),('fixture-no-assets',False),('fixture-inactive',True)]:
        directory=WORKSPACE/'node_modules'/name;(directory/'lib/assets').mkdir(parents=True)
        exports={'.':'./host.js','./client':'./client.js'}
        if export:exports.update({'./assets/private/*':None,'./assets/*':'./lib/assets/*'})
        (directory/'package.json').write_text(json.dumps(dict(name=name,type='module',version='1.0.0',exports=exports,
            dsh=dict(client=dict(platform='web')))),encoding='utf-8')
        (directory/'host.js').write_text('export default () => {}',encoding='utf-8')
        (directory/'client.js').write_text('module.exports={};',encoding='utf-8')
        assets=directory/'lib/assets'
        for file,body in [('icon.svg',b'<svg><script>alert(1)</script></svg>\n'),('photo.png',b'\x89PNG\r\n\x1a\n\1'),
            ('nested/a b.webp',b'RIFF....WEBP'),("whale(2x)!'.png",b'special png'),('notes.txt',b'text'),
            ('folder.png/inner.png',b'directory'),('private/hidden.png',b'private'),('a',b'fragment'),('100%.png',b'percent'),
            ('large.png',b'\7'*(160*1024))]:
            path=assets/file;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
        (directory/'secret.png').write_bytes(b'secret')
    path=output/'inputs.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE))),encoding='utf-8')
    hashes=output/'fixture-inputs.json';hashes.write_text(json.dumps({str(file.relative_to(WORKSPACE)):hashlib.sha256(file.read_bytes()).hexdigest()
        for file in WORKSPACE.rglob('*') if file.is_file()},indent=2),encoding='utf-8')
    return [path,hashes]


def loader(workspace):
    entries=[NS(options=dict(name=name),fiber=NS(),disabled=False,parent=NS(tree=NS(ctx=NS(baseUrl=workspace.as_uri()+'/')))) for name in [NAME,'fixture-no-assets']]
    return NS(entries=lambda:iter(entries))


async def response_bytes(result):
    body=result.get('body')
    if body is None:return b''
    if isinstance(body,bytes):return body
    try:return b''.join([chunk async for chunk in body])
    finally:await body.aclose()


async def observe(workspace=None):
    from dsh.cordis import Context
    from dsh.host.client_modules.current import CurrentClientModuleRegistry
    workspace=workspace or WORKSPACE;ctx=Context();ctx.provide('loader',loader(workspace));rows=[]
    try:
        registry=CurrentClientModuleRegistry(ctx)
        async def request(stage,path,method='GET',tag=None):
            result=await registry.fetchBundle(dict(url='http://x'+path,method=method,headers={'If-None-Match':tag} if tag else {}))
            body=await response_bytes(result)
            rows.append(dict(stage=stage,status=result['status'],headers=result['headers'],length=len(body),sha256=hashlib.sha256(body).hexdigest()))
        for case in CASES:await request(case[0],'/plugins/'+NAME+'/assets/'+case[1],*case[2:])
        await request('no-export','/plugins/fixture-no-assets/assets/photo.png')
        await request('inactive','/plugins/fixture-inactive/assets/photo.png')
        return rows
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_client_assets.mts',prepare=prepare,
        scope='Actual Source/Native asset export ownership, exact response headers and body SHA-256/length, cache/method behavior, encoded paths, export exclusions, directories and inactive packages.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/host/client_modules/current.py',ROOT/'dsh/host/client_modules/assets_current.py',ROOT/'dsh/boot/package_resolution.py'])
