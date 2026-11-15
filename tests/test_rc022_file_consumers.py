import os

import pytest

from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.fs.local_current import CurrentFsLocal
from dsh.fs.fs_observation_policy import CurrentFsObservationPolicy
from dsh.fs.tools_current import CurrentPatchToolFs
from scripts import rc022_file_consumers_probe as probe
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_tool_callbacks_canonical_paths_and_typed_validation():
    rows={row['name']:row for row in await probe.observe()}
    assert len(rows)==29
    for name in ('read-whole','read-stream','read-unknown','read-window','write-create','write-update','write-identical','edit','edit-all'):
        row=rows[name]
        assert row['result']['value']['path']=='/canonical/file.ts'
        assert row['result']['meta']['path']=='/canonical/file.ts'
        assert row['observations'][0]['path']=='/display/file.ts'
        assert row['calls'][0]=='directory'
    assert 'stream' in rows['read-stream']['calls'] and 'read' not in rows['read-stream']['calls']
    assert 'stream' in rows['read-unknown']['calls']
    assert rows['write-identical']['result']['presentation']['diffs']==[dict(path='/canonical/file.ts',oldText=None,newText='new\n')]
    assert rows['write-update']['result']['meta']['operation']=='update'
    for tool in ('read','write','edit'):
        assert rows[tool+'-blank']['result']['error']['code']=='INVALID_ARGS'
        assert rows[tool+'-blank']['calls']==[]
        assert 'error' not in rows[tool+'-not-js-whitespace']['result']
    assert rows['read-offset']['result']['error']['code']=='INVALID_ARGS'
    assert rows['edit-noop']['result']['error']['code']=='INVALID_ARGS'
    assert rows['read-missing']['observations']==[dict(path='/display/file.ts',kind='absent')]
    assert rows['read-directory']['observations']==[]
    assert rows['edit']['withoutEdit']['tool:edit']==''
    assert 'prefer edit' not in rows['write-create']['withoutEdit']['tool:write']


@pytest.mark.asyncio
async def test_real_junction_alias_read_edit_and_identical_write_replay(tmp_path):
    import _winapi
    workspace=tmp_path/'workspace';workspace.mkdir();physical=tmp_path/'physical';physical.mkdir()
    path=physical/'file.ts';path.write_bytes(b'old\n');alias=workspace/'alias';_winapi.CreateJunction(str(physical),str(alias))
    fixture=await setup(tmp_path/'runtime',script=[],directory=workspace);ctx=fixture.ctx
    await ctx.plugin(CurrentFsLocal,dict(cwd=str(tmp_path)))
    await ctx.plugin(CurrentFsObservationPolicy);await ctx.plugin(CurrentPatchToolFs)
    lease=await ctx.agents.create(dict(sessionId='files',agentOptions=dict(provider='script',model='model')))
    async def call(name,arguments):return await ctx.tools.execute(ToolExecutionInput('file-call',name,arguments,agent=lease.agent,signal=NEVER_ABORTED))
    def canonical(value):return os.path.normcase(os.path.normpath(value))
    try:
        read=await call('read',dict(file_path='alias/file.ts'))
        assert not read.is_error, read.content
        assert canonical(read.value['path'])==canonical(str(path))
        assert canonical(read.meta['path'])==canonical(str(path))
        edit=await call('edit',dict(file_path='alias/file.ts',old_string='old',new_string='new'))
        assert not edit.is_error, edit.content
        assert canonical(edit.meta['diffs'][0]['path'])==canonical(str(path))
        assert path.read_bytes()==b'new\n'
        write=await call('write',dict(file_path='alias/file.ts',content='new\n'))
        assert not write.is_error and write.meta['diffs']==[]
        view=ctx.tools.get('write').present_result(dict(file_path='alias/file.ts',content='new\n'),dict(isError=write.is_error,meta=write.meta,content=write.content))
        assert canonical(view['diffs'][0]['path'])==canonical(str(path))
        assert os.path.isdir(alias)
    finally:
        await lease.dispose();await ctx.fiber.dispose();alias.rmdir()


@pytest.mark.asyncio
async def test_real_current_validation_happens_before_directory_lookup(tmp_path):
    fixture=await setup(tmp_path/'runtime',script=[]);ctx=fixture.ctx;lookups=[]
    async def ensure(*_):lookups.append(True);raise RuntimeError('directory must not run')
    ctx.workingDirectory.ensure=ensure;await ctx.plugin(CurrentFsLocal,dict(cwd=str(tmp_path)));await ctx.plugin(CurrentPatchToolFs)
    lease=await ctx.agents.create(dict(sessionId='validation',agentOptions=dict(provider='script',model='model')))
    try:
        for name,arguments in [('read',dict(file_path='\ufeff')),('write',dict(file_path=' \ufeff ',content='')),('edit',dict(file_path='file',old_string='',new_string='new'))]:
            result=await ctx.tools.execute(ToolExecutionInput('invalid',name,arguments,agent=lease.agent,signal=NEVER_ABORTED))
            assert result.is_error and result.error['info']['code']=='INVALID_ARGS'
        assert lookups==[]
    finally:await lease.dispose();await ctx.fiber.dispose()
