"""Manager detail Remote and scoped Connection image-route integration."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    import dsh
    from dsh.boot.app_boot import boot
    from dsh.boot.plugin_manager_current import CurrentPluginManager
    from dsh.boot.plugin_bundle_metadata import OFFICIAL_CATALOG
    from dsh.boot.profile_context import read_profile_patches
    from dsh.cordis.service import Service
    from dsh.typert.remote import remote_error_of
    from dsh.util import plugin_detail_http
    original_version,original_fetch=dsh.__version__,plugin_detail_http.fetch_body
    dsh.__version__='0.2.2-rc.3'
    routes={};requests=[]
    class Connection(Service):
        def __init__(self,ctx,config=None):
            super().__init__(ctx,'connection')
            def register(route):
                routes[route['path']]=route
                return lambda:routes.pop(route['path'],None)
            self.fetch=NS(register=register)
    async def fetch(url,max_bytes,signal,options):
        requests.append(url)
        if '/locale/en.json' in url:return dict(ok=True,bytes=b'{"meta":{"detail":"DETAIL.md"}}')
        if url.endswith('/DETAIL.md'):return dict(ok=True,bytes=b'# Offered')
        if url.endswith('/images/a.svg'):return dict(ok=True,bytes=b'<svg/>')
        return dict(ok=False,status=404)
    plugin_detail_http.fetch_body=fetch
    home=(workspace or WORKSPACE)/'native';directory=home/'profile'
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')
    write(home/'package.json',dict(name='installation'))
    write(directory/'package.json',dict(name='profile',dependencies={name:'1.0.0' for name in ('documented','plain','bare','broken')},dsh=dict(profile=dict(bundles=['core','documented']))))
    for name in ('core','documented','plain','bare','broken'):
        package=directory/'node_modules'/name
        write(package/'package.json',dict(name=name,version='1.0.0',dsh=dict(bundle=dict(patch='patch.yml'))))
        write(package/'patch.yml',[dict(insert=[dict(id='manager',name='cordis:manager'),dict(id='connection',name='cordis:connection')])] if name=='core' else [])
    package=directory/'node_modules/documented'
    write(package/'locale/en.json',dict(meta=dict(detail='guide/DETAIL.md')))
    write(package/'locale/zh.json',dict(meta=dict(detail='guide/DETAIL.zh.md')))
    (package/'guide/img').mkdir(parents=True)
    (package/'guide/DETAIL.md').write_bytes(b'---\ntitle: x\n---\n# Documented\n')
    (package/'guide/DETAIL.zh.md').write_bytes('# Localized'.encode('utf-8'))
    (package/'guide/img/a.svg').write_bytes(b'<svg/>')
    (directory/'node_modules/plain/readme.md').write_bytes(b'# Plain')
    write(directory/'node_modules/broken/locale/en.json',dict(meta=dict(detail='../outside.md')))
    write(directory/'cordis.yml',[]);write(directory/'cordis.patch.yml',[])
    profile=dict(name='test',dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(home/'package.json'),cwd=str(home),home=str(home),startedBundles=['core','documented'],overlays=[])
    def setup(ctx):
        ctx.provide('profileContext',profile)
        ctx.loader.builtins.update(manager=CurrentPluginManager,connection=Connection)
    ctx=None
    try:
        ctx=await boot('test',str(directory/'cordis.yml'),read_profile_patches('test',profile),setup)
        manager=ctx.pluginManager;rows=[]
        async def document(name,language='en',options=None):
            try:return dict(value=await manager.readBundleDetail(name,language,options))
            except Exception as error:
                failure=remote_error_of(error)
                if failure is None:raise
                return dict(error=dict(code=failure['code'],details=failure['details']))
        for name,language in [('documented','zh-CN'),('documented','en'),('plain','en'),('bare','en'),('broken','en'),('documented','../x'),('unknown','en')]:
            rows.append(dict(kind='document',name=name,language=language,result=await document(name,language)))
        offered=OFFICIAL_CATALOG[0]['packageName']
        rows.append(dict(kind='offered',result=await document(offered,'en',dict(npmFileSources=['unpkg'])),requests=list(requests)))
        route=routes['/api/plugin-manager/detail-file']
        rows.append(dict(kind='route',methods=route['methods'],body=route['requestBody']))
        async def image(params):
            response=await routes['/api/plugin-manager/detail-file']['fetch'](dict(url='http://localhost/api/plugin-manager/detail-file?'+urlencode(params)))
            if isinstance(response['body'],bytes):response['body']=response['body'].decode('utf-8')
            return response
        for params in [dict(),dict(bundle='documented',document='guide/DETAIL.md',path='img/a.svg'),
                       dict(bundle='documented',document='guide/DETAIL.md',path='../../outside.png'),
                       dict(bundle='unknown',document='README.md',path='img.png'),
                       dict(bundle=offered,document='DETAIL.md',path='images/a.svg',sources='unpkg')]:
            rows.append(dict(kind='image',result=await image(params)))
        (package/'guide/img/a.svg').write_bytes(b'<svg>new</svg>')
        rows.append(dict(kind='fresh-image',result=await image(dict(bundle='documented',document='guide/DETAIL.md',path='img/a.svg'))))
        manager.detail['maxImageBytes']=2
        rows.append(dict(kind='image-limit',result=await image(dict(bundle='documented',document='guide/DETAIL.md',path='img/a.svg'))))
        manager.detail['maxDocumentBytes']=2
        rows.append(dict(kind='document-limit',result=await document('documented')))
        await ctx.loader.resolve('include:manager').fiber.dispose()
        rows.append(dict(kind='disposed-route',remaining=list(routes)))
        return rows
    finally:
        if ctx is not None:await ctx.fiber.dispose()
        dsh.__version__,plugin_detail_http.fetch_body=original_version,original_fetch


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_manager_detail.mts','Actual manager boot through Include/Loader with injected Connection registry. Local and offered localized details, not-found/invalid failures, preferred CDN, MIME/security/no-store image route, traversal refusal, replacement reads, byte limits and route removal when manager unloads. Controlled CDN replies use actual shared readers; transport separately qualified.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_manager_current.py',ROOT/'dsh/boot/plugin_bundle_detail.py',ROOT/'dsh/util/plugin_detail_http.py'],prepare=prepare)
