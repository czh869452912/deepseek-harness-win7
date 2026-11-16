"""Document selection, local-file reads and image-response primitives."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def corpus():
    return dict(languages=['zh-Hans-CN','en-US','en','ZH-cn','a','../x','en_Us','abcdefgh-12345678','en-123456789','en\n','\u0130D'],
        paths=[None,True,3,'',' ','x.md','guide/file.markdown','/x.md','../x.md','./x.md','guide//x.md','a\\b.md','https:x.md','C:x.md','x.txt','x.MD','x.md\n','\ufeff'],
        images=[dict(document=doc,authored=path) for doc in ('README.md','docs/guide.md') for path in ['a.png','../a.PNG','../../a.png','/images/a.svg','//images/a.png','///images/a.png','https://example/a.png','%2e%2e/a.jpg','a%20b.webp?x#f','a%ZZ.png','a%00.png','a%5cb.png','%FF.png','a.png/','a.png/.','a.png/..','a.exe','data:a.png','.png','foo//a.png','a%3fb.png']],
        markdown=['# A','\ufeff---\ntitle: x\n---\n# A\n\n---\nkeep\n---','---\r\nx: v\r\n---','---\nno end','\ufeff\ufeff# B'],
        documents=[dict(name='locale',files={'locale/zh-CN.json':json.dumps(dict(meta=dict(detail='guide/x.md'))),'guide/x.md':'---\ntitle: A\n---\n# Local','README.md':'fallback'},language='zh-CN'),
            dict(name='fallback',files={'locale/zh.json':'{"meta":{}}','locale/en.json':'{"meta":{"detail":"en.md"}}','en.md':'English'},language='zh-Hant'),
            dict(name='case-order',files={'README.markdown':'markdown','README.MD':'upper','readme.md':'lower'},language='en'),
            dict(name='invalid',files={'locale/en.json':'{'},language='en'),dict(name='missing',files={'locale/en.json':'{"meta":{"detail":"GONE.md"}}'},language='en'),
            dict(name='no-document',files={},language='en'),dict(name='too-large',files={'README.md':'x'*101},language='en'),
            dict(name='first-locale',files={'locale/zh-cn.json':'{}','locale/zh-CN.json':'{"meta":{"detail":"wrong.md"}}','README.md':'readme'},language='zh-CN'),
            dict(name='scalar-meta',files={'locale/en.json':'{"meta":[]}','README.md':'readme'},language='en'),
            dict(name='null-detail',files={'locale/en.json':'{"meta":{"detail":null}}','README.md':'fallback'},language='en')])


def result(operation):
    try:return dict(value=operation())
    except Exception as error:return dict(error=getattr(error,'reason','error'))


async def observe(workspace=None):
    from dsh.util import plugin_detail as d
    data=corpus();rows=[]
    for language in data['languages']:rows.append(dict(kind='language',input=language,result=result(lambda:d.language_chain(language))))
    for path in data['paths']:rows.append(dict(kind='path',input=path,result=result(lambda:d.detail_path(path))))
    for item in data['images']:rows.append(dict(kind='image',input=item,value=d.detail_image(item['document'],item['authored'])))
    for text in data['markdown']:rows.append(dict(kind='markdown',input=text,value=d.markdown_of(text.encode('utf-8'))))
    rows.append(dict(kind='sources',value=d.npm_file_source_order(['jsdelivr','unpkg','npmmirror'],['unknown','npmmirror','jsdelivr'])))
    rows.append(dict(kind='encoding',value=d.encode_path('guide/a b/\u4e2d\u6587%?#.png')))
    for item in data['documents']:
        reads=[]
        async def read(path,max_bytes,signal):
            reads.append(path)
            if path not in item['files']:return None
            value=item['files'][path].encode('utf-8')
            if len(value)>max_bytes:raise d.DetailFailure('too-large',path)
            return value
        async def readme(directory,max_bytes,signal):
            prefix=directory+'/' if directory else ''
            name=d.readme_name([path[len(prefix):] for path in item['files'] if path.startswith(prefix)])
            return None if name is None else dict(path=prefix+name,bytes=await read(prefix+name,max_bytes,signal))
        try:value=dict(value=await d.read_package_document(NS(read=read,readme=readme),'',d.language_chain(item['language']),100))
        except Exception as error:value=dict(error=getattr(error,'reason','error'))
        rows.append(dict(kind='document',name=item['name'],result=value,reads=reads))
    home=(workspace or WORKSPACE)/'native';home.mkdir(parents=True)
    for filename,text in [('README.md','# One'),('README.markdown','fallback'),('guide/x.md','guide')]:
        path=home/filename;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(text.encode('utf-8'))
    (home.parent/'outside.md').write_text('outside',encoding='utf-8')
    (home/'directory').mkdir()
    files=d.LocalFiles(str(home),'1')
    for path in ('README.md','missing.md','../outside.md','directory','guide/x.md'):
        try:
            value=await files.read(path,100)
            value=dict(value=None if value is None else value.decode('utf-8'))
        except d.DetailFailure as error:value=dict(error=error.reason)
        rows.append(dict(kind='local',path=path,result=value))
    rows.append(dict(kind='local-too-large',result=await async_result(lambda:files.read('README.md',2))))
    readme=await files.readme('',100)
    rows.append(dict(kind='local-readme',value=None if readme is None else dict(path=readme['path'],text=readme['bytes'].decode('utf-8'))))
    for outcome in (None,'invalid','too-large','network','denied','git-unavailable',dict(bytes=b'<svg/>',mediaType='image/svg+xml')):
        response=d.detail_image_response(outcome,'private, max-age=30')
        if isinstance(response['body'],bytes):response['body']=response['body'].decode('utf-8')
        rows.append(dict(kind='response',value=response))
    return rows


async def async_result(operation):
    try:return dict(value=await operation())
    except Exception as error:return dict(error=getattr(error,'reason','error'))


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),data=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_plugin_detail.mts','Language chains and localized Markdown selection, README ranking and missing/invalid/oversized files, front matter/BOM decoding, image destination normalization and MIME allowlist, CDN source ordering/path encoding, real bounded local files and response status/security/cache headers. No HTTP fetch or manager activation in this primitive batch.',[Path(__file__).resolve(),ROOT/'dsh/util/plugin_detail.py'],prepare=prepare)
