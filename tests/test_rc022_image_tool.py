import io
import os
from pathlib import Path

import pytest
from PIL import Image

from dsh.attachment.error import AttachmentError
from dsh.attachment.store_current import CurrentLocalAttachmentStore
from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.fs.local_current import CurrentFsLocal
from dsh.fs.fs_observation_policy import CurrentFsObservationPolicy
from dsh.fs.tools_current import CurrentPatchToolFs
from dsh.llm.error import HarnessError
from scripts import rc022_image_tool_probe as probe
from scripts.oracles.agent_machine_current_python import ScriptAdapter
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_image_callbacks_exact_admission_store_errors_and_identity():
    rows={row['name']:row for row in await probe.observe()}
    assert len(rows)==35
    for name in ('success','sniffed','downscaled','routed'):
        row=rows[name]
        assert row['result']['value']['path']=='C:/canonical/image.PNG'
        assert row['observations']==[dict(path='C:/display/image.PNG',kind='present',version='v1')]
        assert row['calls'][-1]['saveImage']['name']=='image.PNG'
        assert row['result']['content'][1]['type']=='image'
    for name in ('blank','extension','missing-store','deployment','no-agent','no-llm','text-model'):
        assert rows[name]['observations']==[] and 'directory' not in rows[name]['calls']
    assert rows['blank']['result']['error']['code']=='INVALID_ARGS'
    assert rows['text-model']['result']['error']['code']=='IMAGE_UNSUPPORTED_MODEL'
    assert rows['deployment']['result']['error']['code']=='IMAGE_UNSUPPORTED_FORMAT'
    assert rows['missing-file']['observations']==[dict(path='C:/display/image.PNG',kind='absent')]
    assert rows['save-INVALID_IMAGE']['result']['error']['causeOriginal']
    assert rows['save-INVALID_IMAGE']['result']['error']['name']=='AttachmentError'
    assert rows['save-ATTACHMENT_NOT_FOUND']['result']['error']['original']
    assert rows['foreign']['result']['error']['original']
    assert rows['save-IMAGES_TOO_LARGE']['result']['error']['code']=='IMAGES_TOO_LARGE'


class VisionAdapter(ScriptAdapter):
    def resolve_model(self,provider,model):
        return dict(provider=provider,id=model,name=model,inputModalities=['text','image'])


@pytest.mark.asyncio
async def test_real_store_agent_runtime_image_reference_and_typed_decode_failure(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir();home=tmp_path/'attachments';home.mkdir()
    data=io.BytesIO();Image.new('RGB',(2,3),'red').save(data,format='PNG');(workspace/'image.png').write_bytes(data.getvalue());(workspace/'broken.png').write_bytes(b'\x89PNG\r\n\x1a\nnot a png')
    fixture=await setup(tmp_path/'runtime',script=[],directory=workspace);ctx=fixture.ctx
    await ctx.plugin(CurrentFsLocal,dict(cwd=str(tmp_path)));await ctx.plugin(CurrentFsObservationPolicy)
    ctx.llm.registerAdapter(['vision'],VisionAdapter(dict(script=[])))
    tool_owner=await ctx.plugin(CurrentPatchToolFs)
    assert ctx.tools.get('read_image') is None
    store=CurrentLocalAttachmentStore(config=dict(dshHome=str(home)))
    class StoreProvider(Plugin):
        def apply(self,scope):scope.set_service('attachments',store)
    store_owner=await ctx.plugin(StoreProvider)
    lease=await ctx.agents.create(dict(sessionId='images',agentOptions=dict(provider='vision',model='image-model')))
    async def call(path):return await ctx.tools.execute(ToolExecutionInput('image-call','read_image',dict(file_path=path),agent=lease.agent,signal=NEVER_ABORTED))
    try:
        assert ctx.tools.get('read_image') is not None
        result=await call('image.png')
        assert not result.is_error,result.content
        assert Path(result.value['path']).resolve()==(workspace/'image.png').resolve()
        assert result.meta==dict(path=result.value['path'])
        ref=result.value['image'];assert Path(store.imageHostPath(ref)).is_file()
        assert result.content[1]['attachment']['attachmentId']==ref['attachmentId']
        failure=await call('broken.png')
        assert failure.is_error and failure.error['info']['code']=='INVALID_IMAGE'
        assert failure.error['info']['name']=='AttachmentError'
        assert 'truncated or corrupt' in failure.content[0]['text']
        assert isinstance(AttachmentError('typed','INVALID_IMAGE'),HarnessError)
        await store_owner.dispose()
        assert ctx.tools.get('read_image') is None
        await tool_owner.dispose()
    finally:
        await lease.dispose();await ctx.fiber.dispose()
        # Only this fixture's content-addressed immutable outputs need writable teardown.
        for path in home.rglob('*'):
            if path.is_file():os.chmod(str(path),0o600)
