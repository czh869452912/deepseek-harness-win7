"""Actual Sharp/Pillow target encoding and cache behavior, with separate codec bytes."""
import hashlib
import io
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

ACTIVE=None


def prepare(output):
    global ACTIVE
    from PIL import Image
    files=output/'files';files.mkdir()
    entries=[]
    for index,(width,height,target) in enumerate([
        (1224,1429,dict(width=1187,height=1386,maxBytes=2000000)),
        (2048,2048,dict(width=1302,height=1302,maxBytes=2000000)),
        (8000,40,dict(width=4096,height=20,maxBytes=2000000)),
        (1600,900,dict(width=854,height=480,maxBytes=2000000)),
        (900,1600,dict(width=480,height=854,maxBytes=2000000)),
        (8,4,dict(width=80,height=40,maxBytes=2000000)),
        (1,1,dict(width=1,height=1,maxBytes=1)),
        (101,37,dict(width=30,height=11,maxBytes=2000000)),
    ]):
        for alpha in (False,True):
            image=Image.new('RGBA' if alpha else 'RGB',(width,height),(12,34,56,128) if alpha else (12,34,56))
            stream=io.BytesIO();image.save(stream,format='PNG');data=stream.getvalue()
            path=files/('%s-%s.png' % (index,int(alpha)));path.write_bytes(data)
            ref=dict(attachmentId='sha256:'+hashlib.sha256(data).hexdigest(),mediaType='image/png',width=width,height=height,bytes=len(data))
            entries.append(dict(file=str(path.resolve()),ref=ref,target=target,alpha=alpha))
    invalid=[]
    for target in ({},dict(width=0,height=1,maxBytes=1),dict(width=1,height=1.5,maxBytes=1),dict(width=1,height=1,maxBytes=0),
        dict(width=True,height=1,maxBytes=1),dict(width=1,height=None,maxBytes=1),dict(width=1,height=1,maxBytes=9007199254740992)):
        invalid.append(target)
    ACTIVE=dict(entries=entries,invalid=invalid,files=str(files.resolve()))
    path=output/'inputs.json';path.write_text(json.dumps(ACTIVE,ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    from dsh.attachment.images_current import read_request_image
    from dsh.attachment.local import request_image_variant_id
    from dsh.core.abort import AbortController
    rows=[];files=Path(ACTIVE['files'])
    for index,entry in enumerate(ACTIVE['entries']):
        root=files/('native-'+str(index));ref,target=entry['ref'],entry['target'];original=Path(entry['file']).read_bytes()
        stored=dict(ref=ref,data=original)
        initial=await read_request_image(str(root),stored,target)
        variant=str(initial['variantId']);cache=root/'request-images'/variant[7:9]/variant[7:]
        cached=cache.exists()
        if cached:cache.write_bytes(b'corrupt owned cache')
        repeated=await read_request_image(str(root),stored,target)
        controller=AbortController();reason=RuntimeError('caller aborted');controller.abort(reason)
        same_reason=False
        try:await read_request_image(str(root),stored,target,controller.signal)
        except Exception as error:same_reason=error is reason
        ids=[str(request_image_variant_id(ref,dict(target,**override))) for override in (dict(width=target['width']+1),dict(height=target['height']+1),dict(maxBytes=target['maxBytes']+1))]
        rows.append(dict(kind='encoded',index=index,width=initial['width'],height=initial['height'],mediaType=initial['mediaType'],
            hasAlpha=initial['hasAlpha'],depth=initial['depth'],space=initial['space'],withinBytes=initial['bytes']<=target['maxBytes'],
            original=initial['data']==original,cached=cached,repairEqual=repeated['data']==initial['data'],sameAbortReason=same_reason,
            identityStable=variant==str(request_image_variant_id(ref,dict(target))),identityChanges=[variant!=other for other in ids],
            durableUnchanged=Path(entry['file']).read_bytes()==original))
    first=ACTIVE['entries'][0];stored=dict(ref=first['ref'],data=Path(first['file']).read_bytes())
    for index,target in enumerate(ACTIVE['invalid']):
        try:await read_request_image(str(files/'native-invalid'),stored,target);result=dict(value='accepted')
        except Exception as error:result=dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None))
        rows.append(dict(kind='invalid',index=index,**result))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_image_targets.mts','Actual Sharp/Pillow request target geometry, cache reuse/repair, no enlargement, byte target exhaustion, alpha, invalid target diagnostics, abort identity and target-complete variant identity. Encoded bytes and digest values remain codec-specific and are compared only within each implementation.',
        [Path(__file__).resolve(),ROOT/'dsh/attachment/images_current.py',ROOT/'dsh/attachment/image_codec.py',ROOT/'dsh/attachment/local.py'],prepare=prepare)
