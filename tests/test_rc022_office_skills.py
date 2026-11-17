import asyncio
import json
import shutil
import threading
from pathlib import Path

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.skill import office_current as module
from dsh.skill.registry import SkillRegistry
from scripts.rc022_office_skills_probe import observe,cases


@pytest.mark.asyncio
async def test_actual_office_catalog_resources_environment_and_failures(tmp_path):
    rows=await observe(tmp_path/'files')
    (tmp_path/'office-skills-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==17
    for row in rows:
        assert row['catalog']['complete'] and row['after']['complete']
        assert row['removed']==[] and row['recovered']['name']=='office-docx'
        assert row['warnings'] in (0,1)
    assert 'load_workspace_dependencies' in rows[0]['loaded'][1]['content']
    assert "user's existing Python" in rows[1]['loaded'][1]['content']
    assert rows[0]['loaded'][0]['content']==rows[1]['loaded'][0]['content']
    assert rows[-1]['loaded'][1] is None and rows[-1]['warnings']==1


@pytest.mark.asyncio
@pytest.mark.parametrize('error',[PermissionError('locked'),OSError('temporary')])
async def test_transient_discovery_retries_and_get_preserves_error_identity(tmp_path,monkeypatch,error):
    original=module._read_file;broken=[True]
    def read(path):
        if 'office-docx' in path and broken[0]:raise error
        return original(path)
    monkeypatch.setattr(module,'_read_file',read)
    ctx=Context();warnings=[];ctx.logger.warn=lambda message,*args:warnings.append(str(message))
    try:
        await ctx.plugin(SkillRegistry);await ctx.plugin(module.CurrentOfficeSkills)
        first=await ctx.skills.snapshot();assert not first['complete'] and len(first['skills'])==3
        broken[0]=False;assert (await ctx.skills.snapshot())['complete']
        broken[0]=True
        with pytest.raises(type(error)) as caught:await ctx.skills.get('office-docx')
        assert caught.value is error
        assert len(warnings)==2
        broken[0]=False;assert 'python-docx' in (await ctx.skills.get('office-docx'))['content']
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_preaborted_provider_read_does_not_warn_or_touch_fs(monkeypatch):
    registered=[];ctx=Context();warnings=[];ctx.logger.warn=lambda *args:warnings.append(args)
    class Skills:
        def registerProvider(self,create):registered.append(create)
    ctx.set_service('skills',Skills())
    monkeypatch.setattr(module,'_read_file',lambda path:(_ for _ in ()).throw(AssertionError('unexpected read')))
    try:
        await ctx.plugin(module.CurrentOfficeSkills)
        provider=registered[0](None);abort=AbortController();abort.abort()
        with pytest.raises(Exception) as caught:await provider.list(dict(signal=abort.signal))
        assert getattr(caught.value,'name',None)=='AbortError' and warnings==[]
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_invalidated_body_removes_cached_candidate_and_deduplicates_warning(tmp_path):
    root=tmp_path/'assets';shutil.copytree(str(module.ASSETS),str(root));ctx=Context();warnings=[]
    ctx.logger.warn=lambda message,*args:warnings.append(str(message))
    try:
        await ctx.plugin(SkillRegistry);await ctx.plugin(module.CurrentOfficeSkills,dict(assetRoot=str(root)))
        assert len(await ctx.skills.list())==4
        (root/'office-docx'/'SKILL.md').write_text('---\ndescription: [unclosed\n---\nBody',encoding='utf-8')
        assert await ctx.skills.get('office-docx') is None
        after=await ctx.skills.snapshot();assert after['complete'] and len(after['skills'])==3
        assert await ctx.skills.get('office-docx') is None and len(warnings)==1
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_inflight_abort_and_disposal_drain_owned_file_read(monkeypatch):
    entered=threading.Event();release=threading.Event();original=module._read_file
    def read(path):
        if 'office-docx' in path:entered.set();release.wait(10)
        return original(path)
    monkeypatch.setattr(module,'_read_file',read)
    ctx=Context();warnings=[];ctx.logger.warn=lambda *args:warnings.append(args)
    await ctx.plugin(SkillRegistry);fiber=await ctx.plugin(module.CurrentOfficeSkills)
    abort=AbortController();listing=asyncio.create_task(ctx.skills.list(dict(signal=abort.signal)))
    try:
        assert await asyncio.get_running_loop().run_in_executor(None,entered.wait,5)
        abort.abort()
        with pytest.raises(Exception):await listing
        disposing=asyncio.ensure_future(fiber.dispose());await asyncio.sleep(0)
        assert not disposing.done()
        release.set();await disposing
        assert warnings==[] and await ctx.skills.list()==[]
    finally:release.set();await ctx.fiber.dispose()
