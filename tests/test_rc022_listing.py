import pytest
from scripts.rc022_listing_probe import observe

@pytest.mark.asyncio
async def test_shared_listing_bound_settles_and_selects_sequential_failure():
    rows=await observe()
    for row in rows[:-1]:
        assert row['peak']==row['limit'] and row['active']==0
        names=row['failures']
        # A failed project prevents its own and all later directory tasks.
        project=next((i for i in range(3) if 'p'+str(i) in names),3)
        directories=['d'+str(i)+str(j) for i in range(project) for j in range(2)]
        first=next((name for name in directories if name in names), 'p'+str(project) if project<3 else None)
        for value in row['values']:
            if first is None:assert value==dict(values=directories)
            else:assert value==dict(error=first,same=True)
        assert row['completed']==sorted(['root','p0','p1','p2']*2+directories*2)
    configs=rows[-1]['configs']
    assert [row.get('limit') for row in configs[:3]]==[3,1,2]
    assert all(row.get('rejected') for row in configs[3:])


@pytest.mark.asyncio
async def test_real_backend_shares_bound_for_headers_stats_and_corpus(tmp_path):
    import asyncio
    from pathlib import Path
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistence
    from dsh.session.jsonl_current import generationLogPath,header_bytes
    for project in ('/work-a','/work-b'):
        for number in range(3):
            header=dict(version=4,id=project[-1]+str(number),cwd=project,createdAt=1,isSeeded=False,delegationDepth=0)
            path=Path(generationLogPath(str(tmp_path),project,header['id'],4,'none'))
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(header_bytes(header,0,4))
    backend=CurrentJsonlSessionPersistence(str(tmp_path),'none',format_version=4,list_concurrency=2)
    await backend.list()
    original=backend._run
    active=peak=0
    async def measured(fn,*args):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        try:
            await asyncio.sleep(0.002)
            return await original(fn,*args)
        finally:active-=1
    backend._run=measured
    try:
        first,second,corpus,artifacts=await asyncio.gather(backend.list(),backend.list(),backend.historicalCorpusRevision(),backend.listArtifacts())
        assert peak==2 and active==0
        assert [row['header']['id'] for row in first]==[row['header']['id'] for row in second]
        assert len(first)==len(artifacts)==6 and len(corpus)==64
    finally:await backend.close()


@pytest.mark.asyncio
async def test_list_checks_abort_after_successful_final_stat(tmp_path):
    from dsh.core.abort import AbortController
    from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistence
    backend=CurrentJsonlSessionPersistence(str(tmp_path),'none',format_version=4)
    controller=AbortController();reason=ValueError('stat completed after abort')
    header=dict(version=4,id='owned',createdAt=1,isSeeded=False,delegationDepth=0)
    async def artifacts(signal):return [dict(header=header,path='owned',sourceVersion=4,formatStatus='current')]
    async def identity(path):
        controller.abort(reason)
        return dict(dev=0,ino=0,size=0,mtimeNs=0,ctimeNs=0)
    backend.listArtifacts=artifacts;backend._physical_identity=identity
    try:
        with pytest.raises(ValueError) as captured:await backend.list(dict(signal=controller.signal))
        assert captured.value is reason
    finally:await backend.close()
