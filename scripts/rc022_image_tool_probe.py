"""Current image tool admission and store failure taxonomy against actual Source."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    cases=[dict(name=name) for name in ['success','sniffed','downscaled','blank','extension','missing-store','deployment','no-agent','no-llm','text-model','routed','missing-file','directory','unknown-signature','sniffed-deployment']]
    codes=['IMAGE_DIMENSION_TOO_LARGE','IMAGE_TOO_MANY_PIXELS','IMAGE_TOO_LARGE','IMAGES_TOO_LARGE','UNSUPPORTED_IMAGE_TYPE','INVALID_IMAGE','IMAGE_TYPE_MISMATCH','ATTACHMENT_WRITE_FAILED','TOO_MANY_IMAGES','INVALID_IMAGE_BASE64','INVALID_FILE_BASE64','INVALID_ATTACHMENT_REF','ATTACHMENT_CORRUPT','ATTACHMENT_NOT_FOUND','ATTACHMENT_READ_FAILED','ATTACHMENT_PROJECTION_UNSUPPORTED','ATTACHMENT_FILES_UNSUPPORTED']
    cases += [dict(name='save-'+code,code=code) for code in codes]
    cases += [dict(name='sniffed-mismatch',code='IMAGE_TYPE_MISMATCH'),dict(name='16-bit',code='ATTACHMENT_WRITE_FAILED',message='16-bit PNG failure'),dict(name='foreign',foreign=True)]
    return cases


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.attachment.error import AttachmentError
    from dsh.fs.fs_local import FsTarget
    from dsh.fs.read_image_current import apply_read_image_tool
    rows=[]
    for case in corpus():
        ctx=Context();calls=[];observations=[];definitions=[];name=case['name'];path='image' if name in ('sniffed','unknown-signature','sniffed-deployment','sniffed-mismatch') else 'file.pdf' if name=='extension' else ' \ufeff ' if name=='blank' else 'file.PNG'
        controller=NS(signal=NEVER_ABORTED)
        class Session:
            def requestHeader(self):return dict(config=dict(provider='routed',model='routed-model')) if name=='routed' else dict(config={})
        agent=None if name=='no-agent' else NS(session=Session(),options=dict(provider='base',model='base-model'))
        async def route(provider,model,signal):calls.append(dict(route=[provider,model],signal=signal is NEVER_ABORTED));return dict(inputModalities=['text'] if name=='text-model' else ['text','image'])
        async def directory(*_):calls.append('directory');return 'C:/working'
        async def resolve(path,options):calls.append(dict(resolve=path,cwd=options.get('cwd')));return FsTarget(target_key='identity',display_path='C:/display/image.PNG')
        async def stat(*_):calls.append('stat');return None if name=='missing-file' else NS(type='directory' if name=='directory' else 'file',version='v1')
        async def read(target,signal,cap):calls.append(dict(readBytes=cap));return b'not image' if name=='unknown-signature' else b'\x89PNG\r\n\x1a\n'
        error=RuntimeError('foreign store failure') if case.get('foreign') else AttachmentError(case.get('message','store failure'),case['code']) if 'code' in case else None
        async def save(input):
            calls.append(dict(saveImage=dict(mediaType=input['mediaType'],name=input['name'],bytes=len(input['data']))))
            if error is not None:raise error
            result=dict(attachmentId='sha256:'+'a'*64,mediaType='image/png',bytes=77,width=2,height=3,name=input['name'])
            if name=='downscaled':result['originalDimensions']=dict(width=5,height=8)
            return result
        ctx.set_service('tools',NS(register=lambda definition:definitions.append(definition)))
        ctx.set_service('workingDirectory',NS(ensure=directory));ctx.set_service('fs',NS(resolve=resolve,stat=stat,readBytes=read,processPath=lambda _:'C:/canonical/image.PNG'))
        if name!='no-llm':ctx.set_service('llm',NS(resolveModelInfo=route))
        if name!='missing-store':ctx.set_service('attachments',NS(imageLimits=dict(mediaTypes=['image/jpeg'] if name in ('deployment','sniffed-deployment') else ['image/png'],maxImageBytes=100,maxMessageImageBytes=80,maxImageDimension=4096,maxImagePixels=100000),saveImage=save))
        ctx.on('fs/observed',lambda target,value,*_:observations.append(dict(path=target.displayPath,**value)))
        try:
            apply_read_image_tool(ctx);definition=definitions[0];arguments=dict(file_path=path)
            try:
                value=await definition['execute'](arguments,NS(agent=agent,signal=NEVER_ABORTED));result=dict(value=value,content=definition['output']['render'](arguments,value),meta=definition['output']['presentationMeta'](arguments,value))
            except Exception as failure:result=dict(error=dict(name=getattr(failure,'name','Error'),code=getattr(failure,'code',None),message=getattr(failure,'message',str(failure)),original=failure is error,causeOriginal=getattr(failure,'cause',None) is error if error is not None else False))
            rows.append(dict(name=name,result=result,calls=calls,observations=observations,definition=dict(name=definition['name'],description=definition['description'],parameters=definition['parameters'],outputSchema=definition['output']['schema']),call=definition['presentCall'](arguments)))
        finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_image_tool.mts','Actual read_image callbacks/schema over ordered collaborators: pre-read model/deployment/format gates, current route, canonical paths, byte cap, async save before authoritative observation, source failure codes/causes/identity, signature sniffing and scaled output.',[Path(__file__).resolve(),ROOT/'dsh/fs/read_image_current.py',ROOT/'dsh/attachment/error.py'],prepare=prepare)
