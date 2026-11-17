import asyncio
import builtins
import json
import threading

import pytest

from scripts.rc022_client_chunks_probe import NAME,prepare,setup,observe


@pytest.mark.asyncio
async def test_current_chunk_observations(tmp_path):
    prepare(tmp_path);rows=await observe(tmp_path/'files')
    (tmp_path/'client-chunks-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    by={row['stage']:row for row in rows}
    assert len(rows)==18
    assert by['script']['body']==by['cached']['body']==by['cached-after-compose']['body']
    assert 'generation:1' in by['script']['body'] and 'generation:2' in by['next-generation']['body']
    assert all(row['status']==404 for row in rows if row['stage'].startswith('blocked-'))
    assert by['prior-rejected']['status']==404 and by['removed']['status']==404
    assert json.loads(by['map']['body'])['file']=='client.terminal.js'
    assert json.loads(by['map']['body'])['sections'][0]['map']['sources']==['/plugins/'+NAME+'/client.terminal.js']


@pytest.mark.asyncio
async def test_current_chunk_read_is_async_and_retries_rejected_body(tmp_path,monkeypatch):
    prepare(tmp_path);workspace=tmp_path/'files';ctx,registry,_=await setup(workspace)
    chunk=workspace/'node_modules'/NAME/'client.excel.js';chunk.write_text('module.exports={loaded:true};',encoding='utf-8')
    chunk.with_suffix('.js.map').write_text('{"version":3,"names":[],"sources":["src/excel.ts"],"mappings":"AAAA"}',encoding='utf-8')
    original=builtins.open;loop_thread=threading.get_ident();threads=[];failed=[]
    def tracked(path,*args,**kwargs):
        if str(path)==str(chunk):
            threads.append(threading.get_ident());assert threads[-1]!=loop_thread
            if not failed:failed.append(True);raise OSError('download failed')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(builtins,'open',tracked)
    url='http://x/plugins/'+NAME+'/'+chunk.name+'?rev='+registry.graph()['entries'][0]['rev']
    try:
        assert (await registry.fetchBundle(dict(url=url,method='HEAD')))['status']==200 and not threads
        with pytest.raises(OSError,match='download failed'):await registry.fetchBundle(dict(url=url,method='GET'))
        left,right=await asyncio.gather(registry.fetchBundle(dict(url=url,method='GET')),registry.fetchBundle(dict(url=url,method='GET')))
        assert left['body'] is right['body'] and len(threads)==2
        mapped=await registry.fetchBundle(dict(url=url.replace('.js?','.js.map?'),method='GET'))
        assert 'src/excel.ts' in mapped['body'].decode('utf-8') and len(threads)==3
    finally:await ctx.fiber.dispose()
