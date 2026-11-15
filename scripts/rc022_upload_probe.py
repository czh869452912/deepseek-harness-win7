"""Pair typed Session-owned upload lifecycle and mixed prompt image budgets."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.attachment.store_current import CurrentAttachmentAPI
    from dsh.attachment.store import AttachmentStore
    from dsh.core.abort import AbortController
    from dsh.host.file_upload_authorized import AuthorizedFileUploads
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];resolvers=[];routes=[];writes=[]
    limits=dict(maxImageBytes=4,maxImagesPerMessage=2,maxMessageImageBytes=6,mediaTypes=['image/png'])
    image=dict(attachmentId='sha256:'+'12'*32,mediaType='image/png',bytes=2,width=1,height=1)
    class Store(CurrentAttachmentAPI,AttachmentStore):
        @property
        def image_limits(self):return limits
        async def saveImages(self,inputs):
            self.validate_image_batch(inputs);writes.append([len(item['data']) for item in inputs]);return [image]*len(inputs)
        async def saveFileStream(self,request):
            data=b''.join([chunk async for chunk in request['data']]);return dict(attachmentId='file',bytes=len(data),name=request.get('name','file'))
    ctx.set_service('attachments',Store())
    def register(resolver):
        resolvers.append(resolver);return lambda:resolvers.remove(resolver)
    def route(value):
        routes.append(value);return lambda:routes.remove(value)
    ctx.set_service('commands',NS(registerFileReceiptResolver=register));ctx.set_service('connection',NS(fetch=NS(register=route)))
    async def chunks(*values):
        for value in values:yield bytes(value)
    async def result(name,callback):
        try:value=await callback();rows.append(dict(name=name,value=value));return value
        except Exception as error:rows.append(dict(name=name,error=dict(code=error.code,details=getattr(error,'details',{}))));return None
    try:
        fiber=await ctx.plugin(AuthorizedFileUploads);uploads=ctx.fileUploads
        agent=(await ctx.agents.create(dict(sessionId='one'))).agent
        other=(await ctx.agents.create(dict(sessionId='two'))).agent
        first=await uploads.uploadImageStream(dict(sessionId='one',mediaType='image/png',data=chunks([1,2],[3])))
        staged=uploads.resolve(agent,first['receiptId'])
        rows.append(dict(name='typed-image',value=staged,foreign=uploads.resolve(other,first['receiptId']),command=resolvers[0](agent,first['receiptId'])))
        file=await uploads.uploadStream(dict(sessionId='one',data=chunks([4,5]),name='file.bin'))
        rows.append(dict(name='typed-file',value=uploads.resolve(agent,file['receiptId']),command=resolvers[0](agent,file['receiptId'])))
        binding=uploads.bindPrompt(agent,[first['receiptId']],'rollback');binding.dispose();uploads.retirePrompt(agent,'rollback')
        rows.append(dict(name='rollback',retained=uploads.resolve(agent,first['receiptId']) is not None))
        binding=uploads.bindPrompt(agent,[first['receiptId']],'accepted');binding.commit();binding.dispose();uploads.retirePrompt(agent,'accepted')
        rows.append(dict(name='committed',retained=uploads.resolve(agent,first['receiptId']) is not None))
        await result('stored-only',lambda:ctx.attachments.admitPromptContent([staged]))
        encoded=dict(type='image',data='AQID',mediaType='image/png')
        await result('mixed-at-limit',lambda:ctx.attachments.admitPromptContent([staged,encoded]))
        await result('mixed-over-bytes',lambda:ctx.attachments.admitPromptContent([dict(staged,encodedBytes=4),encoded]))
        await result('mixed-over-count',lambda:ctx.attachments.admitPromptContent([staged,staged,encoded]))
        await result('upload-over-limit',lambda:uploads.uploadImageStream(dict(sessionId='one',mediaType='image/png',data=chunks([1,2,3],[4,5]))))
        await result('unsupported',lambda:uploads.uploadImageStream(dict(sessionId='one',mediaType='',data=chunks([1]))))
        controller=AbortController();controller.abort()
        await result('cancelled',lambda:uploads.uploadImageStream(dict(sessionId='one',mediaType='image/png',data=chunks([1]),signal=controller.signal)))
        response=await routes[0]['fetch'](dict(method='POST',url='http://host/api/session/uploadFileBinary?sessionId=one&mediaType=image%2Fpng',headers={'content-type':'application/octet-stream'},body=chunks([7,8])))
        body=json.loads(response['body']);rows.append(dict(name='image-route',status=response['status'],ok=body['ok'],image=body['value']['image']))
        rows.append(dict(name='writes',values=writes))
        await fiber.dispose();rows.append(dict(name='unloaded',routes=len(routes),resolvers=len(resolvers)))
        return rows
    finally:await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_upload.mts','Actual typed upload provider and attachment base admission; controlled byte storage, command resolver and Connection route registry. Session ownership, rollback/retirement, image stream limits/cancellation, mixed stored/encoded budgets and image HTTP dispatch.',
        [Path(__file__).resolve(),ROOT/'dsh/host/file_upload_authorized.py',ROOT/'dsh/attachment/store_current.py',ROOT/'dsh/host/file_upload_current.py'],prepare=prepare)
