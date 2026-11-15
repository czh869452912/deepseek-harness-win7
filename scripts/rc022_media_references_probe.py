"""Compare the mounted version-addressed media route against fixed Source."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
CASES=[dict(name='unversioned'),dict(name='stale',v='old'),dict(name='versioned',v='v1'),dict(name='versioned-head',v='v1',method='HEAD'),
       dict(name='unversioned-head',method='HEAD'),dict(name='encoded',path='C:/资料/space +~*#.svg',version='v &~*中文'),
       dict(name='missing-path',path=None),dict(name='empty-path',path=''),dict(name='relative-path',path='relative'),dict(name='nul-path',path='C:/a\0.png'),
       dict(name='absent',info=None),dict(name='directory',info=dict(type='directory',version='v1')),
       dict(name='too-large',info=dict(type='file',size=5,version='v1')),dict(name='size-unknown',info=dict(type='file',version='v1'),v='v1',method='HEAD'),
       dict(name='read-size-unknown',info=dict(type='file',version='v1'),v='v1'),dict(name='unknown-mime',displayPath='C:/x.no-such-extension',v='v1'),
       dict(name='ignored-range',v='v1',range='bytes=0-0')]
CASES += [dict(name='error-'+code,error=code,stage=stage,v='v1',method=method) for code,stage,method in [
    ('FS_NOT_FOUND','stat','GET'),('FS_PERMISSION_DENIED','resolve','HEAD'),('FS_SANDBOX_DENIED','resolve','GET'),
    ('FS_TOO_LARGE','read','GET'),('FS_ABORTED','read','GET'),('FS_IO_ERROR','stat','GET'),('unexpected','read','GET')]]


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.api.session_media_authorized import AuthorizedSessionMediaReferences
    from dsh.fs.fs_local import FsError
    rows=[]
    for case in CASES:
        ctx=Context();calls=[];routes=[];withdrawn=[];target=dict(displayPath=case.get('displayPath','C:/photo.png'))
        def failure(stage):
            if case.get('stage')==stage:
                if case['error']=='unexpected':raise RuntimeError('unexpected provider failure')
                raise FsError('provider failed',case['error'])
        async def resolve(path,options):calls.append(dict(method='resolve',path=path,signal=options['signal'] is NEVER_ABORTED));failure('resolve');return target
        async def stat(received,signal):calls.append(dict(method='stat',sameTarget=received is target,signal=signal is NEVER_ABORTED));failure('stat');return case.get('info',dict(type='file',size=4,version=case.get('version','v1')))
        async def read(received,signal,maximum):calls.append(dict(method='read',sameTarget=received is target,signal=signal is NEVER_ABORTED,maxBytes=maximum));failure('read');return bytearray([0,1,2,255])
        def register(route):routes.append(route);return lambda:withdrawn.append(True)
        ctx.set_service('connection',NS(fetch=NS(register=register)));ctx.set_service('attachments',NS(imageLimits=dict(maxImageBytes=4)))
        ctx.set_service('fs',NS(resolve=resolve,stat=stat,readBytes=read))
        try:
            provider=await ctx.plugin(AuthorizedSessionMediaReferences)
            params={};path=case.get('path','C:/photo.png')
            if path is not None:params['path']=path
            if 'v' in case:params['v']=case['v']
            try:
                result=await routes[0]['fetch'](dict(url='https://host/prefix/api/file?'+urlencode(params),method=case.get('method','GET'),signal=NEVER_ABORTED,headers=dict(range=case.get('range',''))))
                body=result['body'];value=dict(status=result['status'],headers=result['headers'],hex='' if body is None else (body.encode('utf-8') if isinstance(body,str) else body).hex())
            except Exception as error:value=dict(error=str(error))
            await provider.dispose();rows.append(dict(name=case['name'],value=value,calls=calls,withdrawn=withdrawn==[True]))
        finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(CASES),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_media_references.mts','Mounted actual media contribution over controlled Connection registration and FS boundaries: version redirects/form encoding, immutable GET/HEAD, pre-read stat/type/size refusal, optional sizes, byte bounds, MIME, Range treatment, error taxonomy and withdrawal. Authentication and actual disk reads are separately qualified by native integration tests.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_media_authorized.py'],prepare=prepare)
