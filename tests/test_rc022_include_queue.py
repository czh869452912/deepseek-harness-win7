"""Actual file/runtime persistence journeys through canonical Loader entries."""
import asyncio
import json
import os

from dsh.cordis import Context, Loader
from dsh.cordis.include import Include

from scripts import rc022_include_queue_probe as probe


def test_independent_edits_conflicts_recovery_patch_ownership_and_failed_refresh(tmp_path):
    probe.OUTPUT=tmp_path
    observed=asyncio.run(probe.native())
    for mode in ('refresh-first','update-first'):
        assert observed[mode]==[[{'value':2},{'value':3}],[probe.row('a',2),probe.row('b',3)],[],0]
    assert observed['conflict']==[[{'value':3},{'value':1}],[probe.row('a',3),probe.row('b',1)],[],0]
    assert observed['recovery']==[[{'value':2},{'value':4}],[probe.row('a',2),probe.row('b',4)],
                                  [['Error',None],['ConfigFileError','parse']],0]
    assert observed['patch']==[True,[{'id':'x','disabled':False},{'insert':[probe.row('y',2)]}]]
    assert observed['failed-refresh']==[[{'value':3},{'value':1}],[probe.row('a',3),probe.row('b',1)],[],0]
    assert observed['duplicate']==[2,['a'],{'value':2}]
    assert observed['missing-import']==[True,1,1,['missing'],True,0]


async def mounted(directory):
    path=directory/'root.json';path.write_text(json.dumps([probe.row('a',1)]),encoding='utf-8')
    ctx=Context();ctx.baseUrl=directory.as_uri()+'/'
    await ctx.plugin(Loader);ctx.loader.builtins['include']=Include
    ctx.loader.builtins['example']=lambda owner,config:None
    key=await ctx.loader.create({'name':'cordis:include','config':{'path':path.as_uri()}})
    await ctx.loader.wait()
    return ctx,ctx.loader.resolve(key).subtree,path


def test_readonly_retains_journal_and_retries_after_access_recovers(tmp_path,monkeypatch):
    async def run():
        ctx,include,path=await mounted(tmp_path);real_access=os.access;readonly=[True]
        monkeypatch.setattr(os,'access',lambda name,mode:False if str(name)==str(path) and readonly[0] else real_access(name,mode))
        try:
            await include.update('a',{'config':{'value':2}})
            try:await include.flush()
            except RuntimeError as error:assert 'unsaved change' in str(error)
            else:raise AssertionError('unwritten journal accepted')
            assert include.journal and json.loads(path.read_text(encoding='utf-8'))==[probe.row('a',1)]
            assert include.store['a'].fiber.effectiveConfig=={'value':2}
            readonly[0]=False;await include.flush()
            assert not include.journal and json.loads(path.read_text(encoding='utf-8'))==[probe.row('a',2)]
        finally:
            readonly[0]=False;await ctx.fiber.dispose()
    asyncio.run(run())


def test_failed_inflight_batch_merges_newer_delta_before_retry(tmp_path):
    async def run():
        ctx,include,path=await mounted(tmp_path);real_write=include._write_text
        entered=asyncio.Event();release=asyncio.Event();attempts=[]
        async def write(text,expected):
            attempts.append(text)
            if len(attempts)==1:
                entered.set();await release.wait();raise OSError('injected write failure')
            await real_write(text,expected)
        include._write_text=write
        try:
            await include.update('a',{'config':{'value':2}});await entered.wait()
            assert not include.journal
            await include.update('a',{'config':{'value':3}})
            assert include.journal['a']['changes']['config']=={'value':3}
            release.set();await include.flush()
            assert len(attempts)==2 and not include.journal
            assert json.loads(path.read_text(encoding='utf-8'))==[probe.row('a',3)]
            assert include.store['a'].fiber.effectiveConfig=={'value':3}
        finally:
            release.set();include._write_text=real_write;await ctx.fiber.dispose()
    asyncio.run(run())
