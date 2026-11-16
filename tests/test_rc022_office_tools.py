import io
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import pytest_asyncio
from PIL import Image

from dsh.attachment.store_current import CurrentLocalAttachmentStore
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.fs.local_current import CurrentFsLocal
from dsh.fs.fs_observation_policy import CurrentFsObservationPolicy
from dsh.office.current import CurrentOfficeKit
from dsh.office.tools import CurrentToolOffice
from dsh.office.outputs import _native
from scripts.rc022_subagent_fixture import setup
from test_rc022_image_tool import VisionAdapter
from test_rc022_office_provider import Engine


class ImageEngine(Engine):
    async def renderImages(self,options,signal):
        self.calls.append(('images',options));self.scratch.append(str(Path(options['inputPath']).parent))
        directory=Path(options['outputDir']);Path(_native(str(directory))).mkdir()
        image=io.BytesIO();Image.new('RGB',(2,3),'blue').save(image,format='PNG')
        path=directory/'1.png';Path(_native(str(path))).write_bytes(image.getvalue())
        return dict(images=[dict(index=1,path=str(path),width=2,height=3,page=1,byteLength=len(image.getvalue()))],pageCount=1,dpi=96,missingFonts=['Font'])


@pytest.mark.asyncio
async def test_tool_callback_admission_authority_and_failure_observations():
    from scripts.rc022_office_tools_probe import observe
    rows={item['name']:item for item in await observe()}
    assert len(rows)==30
    for name in ('failed-skill','wrong-skill','invalid-skill','stale-message'):
        assert not rows[name]['after']
    assert rows['header']['before'] and rows['header']['disposed']
    assert rows['message']['after'] and not rows['message']['disposed']
    assert rows['no-kit']['calls']==[] and rows['no-agent']['calls']==[]
    assert 'source exceeds the reserved byte capacity' in rows['too-large']['result']['error']['message']
    assert rows['changed']['result']['error']['code'] is None
    assert rows['owner-error']['result']['value']['operation']=='convert'
    assert rows['scaled']['result']['value']['images'][0]['mediaType']=='image/webp'


@pytest_asyncio.fixture
async def runtime(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir();(workspace/'report.docx').write_bytes(b'PK\x03\x04')
    (workspace/'book.xlsx').write_bytes(b'PK\x03\x04')
    fixture=await setup(tmp_path/'runtime',script=[],directory=workspace);ctx=fixture.ctx
    await ctx.plugin(CurrentFsLocal,dict(cwd=str(workspace)));await ctx.plugin(CurrentFsObservationPolicy)
    ctx.llm.registerAdapter(['vision'],VisionAdapter(dict(script=[])))
    store=CurrentLocalAttachmentStore(config=dict(dshHome=str(tmp_path/'attachments')))
    ctx.set_service('attachments',store);engine=ImageEngine();ctx.set_service('officeKitEngine',engine)
    kit_owner=await ctx.plugin(CurrentOfficeKit,dict(outputDirectory=str(tmp_path/'outputs')))
    owner=await ctx.plugin(CurrentToolOffice)
    lease=await ctx.agents.create(dict(sessionId='office',agentOptions=dict(provider='vision',model='image-model')))
    async def resolve():return await ctx.tools.resolve(dict(agent=lease.agent,signal=NEVER_ABORTED))
    async def call(name,args,tools=None):
        return await ctx.tools.execute(ToolExecutionInput('office-call',name,args,agent=lease.agent,signal=NEVER_ABORTED,toolSet=tools if tools is not None else await resolve()))
    def activate(name='office',failed=False,args=None):
        ctx.emit('tools/result',NS(agent=lease.agent,name='skill',arguments=dict(name=name) if args is None else args),NS(isError=failed))
    value=NS(ctx=ctx,agent=lease.agent,engine=engine,store=store,owner=owner,kit_owner=kit_owner,call=call,resolve=resolve,activate=activate,workspace=workspace)
    try:yield value
    finally:
        await lease.dispose();await ctx.fiber.dispose()
        assert all(not Path(_native(path)).exists() for path in engine.scratch)


@pytest.mark.asyncio
async def test_skill_admission_is_step_scoped_and_unload_reversible(runtime):
    r=runtime;args=dict(input='report.docx',format='txt');before=await r.resolve()
    for name,failed,raw in [('office',True,None),('other',False,None),('office',False,dict(name=[]))]:
        r.activate(name,failed,raw);result=await r.call('office_convert',args)
        assert result.is_error and not r.engine.calls
    r.activate();old=await r.call('office_convert',args,before)
    assert old.is_error
    result=await r.call('office_convert',args)
    assert not result.is_error,result.content
    assert Path(result.value['file']).read_bytes()==b'text'
    assert result.value['bytes']==4 and result.value['pageCount']==2
    assert 'copy' in result.content[0]['text'].lower()
    assert r.ctx.tools.executable('office_convert') is None
    await r.owner.dispose()
    assert (await r.call('office_convert',args)).is_error


@pytest.mark.asyncio
async def test_render_reads_authority_and_returns_real_attachment_reference(runtime):
    r=runtime;r.activate('office-docx')
    result=await r.call('office_render',dict(input='report.docx',pages=[1]))
    assert not result.is_error,result.content
    ref=result.value['images'][0]
    assert (ref['width'],ref['height'])==(2,3)
    assert Path(r.store.imageHostPath(ref)).is_file()
    assert result.content[2]['attachment']['attachmentId']==ref['attachmentId']
    assert result.meta==dict(path=result.value['path'])
    (r.workspace/'report.docx').unlink()
    missing=await r.call('office_render',dict(input='report.docx'))
    assert missing.is_error and 'not found' in missing.content[0]['text']
    assert len(r.engine.calls)==1


@pytest.mark.asyncio
async def test_skill_message_admission_requires_live_session_identity(runtime):
    r=runtime;event=dict(type='user/message',data=dict(source=dict(kind='skill-invocation',name='office')))
    r.agent.session.append('user/message',dict(event['data'],content=[dict(type='text',text='Load office')]),surface_op='append')
    assert not (await r.call('office_render',dict(input='report.docx'))).is_error
    r.ctx.emit('agent/disposed',dict(agent=r.agent))
    assert (await r.call('office_render',dict(input='report.docx'))).is_error


@pytest.mark.asyncio
async def test_missing_engine_and_parameter_checks_precede_conversion(runtime):
    r=runtime;r.activate();await r.kit_owner.dispose()
    invalid=await r.call('office_convert',dict(input='report.docx',format='csv'))
    assert invalid.is_error and 'this file converts to' in invalid.content[0]['text']
    missing=await r.call('office_convert',dict(input='missing.docx',format='txt'))
    assert missing.is_error and 'unavailable' in missing.content[0]['text']
    assert 'do not substitute system soffice' in missing.content[0]['text']
    assert not r.engine.calls


@pytest.mark.asyncio
async def test_workbook_recalculate_uses_owned_temporary_output(runtime):
    r=runtime;r.activate('office-xlsx')
    result=await r.call('office_recalculate',dict(input='book.xlsx',format='xlsx'))
    assert not result.is_error,result.content
    assert Path(result.value['file']).read_bytes()==b'xlsx'
    assert not (r.workspace/'book-recalculated.xlsx').exists()
    r.ctx.emit('session/disposed',r.agent.session);await r.ctx.officeKit.outputs.settle()
    assert not Path(result.value['file']).exists()
