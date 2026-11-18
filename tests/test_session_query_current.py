"""Actual Source/native query results plus cold cache and admission regressions."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.session.current_session import CurrentSessionPlugin
from dsh.session.jsonl_backend_current import CurrentJsonlSessionPersistencePlugin
from dsh.session.query_current import CurrentSessionQueryService,CurrentSessionCorpus,CurrentSqliteSessionQueryEngine,resolve_config,same_snapshots
from dsh.session.session_query import SessionQueryError
from scripts.oracles.session_format_python import observe
from scripts.session_format_oracle import json_equal

CASES=json.loads((Path(__file__).resolve().parents[1]/'scripts/oracles/session_query_current_cases.json').read_text(encoding='utf8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('version',[3,4])
async def test_surface_and_event_windows_snapshot_the_loaded_format(version):
    events=[dict(type='system/message',seq=seq,time=seq+1,surfaceOp='append',data=dict(message=dict(
        id='system-%s' % seq,role='system',source=dict(kind='system-prompt') if version==4 else dict(kind='plugin',plugin='fixture'),
        content=[dict(type='text',text='system %s' % seq)]))) for seq in range(2)]
    header=SimpleNamespace(version=version)
    async def load(session_id,signal=None):
        assert session_id=='format-owner'
        return dict(header=header,events=events,inheritedEventCount=0)
    query=CurrentSessionQueryService(None)
    query._corpus=SimpleNamespace(load=load)
    surface=await query.readSurface('format-owner')
    window=await query.readEvent(dict(sessionId='format-owner',seq=0,after=1))
    assert surface['events']==events and window['events']==events
    assert window['target']==events[0] and window['target'] is not events[0]
    assert all(actual is not original for actual,original in zip(surface['events'],events))


@pytest.mark.parametrize('case',CASES,ids=[case['case'] for case in CASES])
def test_actual_source_query_and_sqlite_handle_journey(case):
    assert json_equal(observe(case),dict(case=case['case'],outcome='value',value=case['expected']))


@pytest.mark.parametrize('key',['persistedReadConcurrency','preparedSessionCacheSize'])
@pytest.mark.parametrize('value',[False,0,-1,1.5,9007199254740992,float('inf'),float('nan'),'4'])
def test_current_sqlite_config_rejects_invalid_safe_positive_values(key,value):
    with pytest.raises(SessionQueryError) as caught:resolve_config(dict(path=':memory:',**{key:value}))
    assert caught.value.code=='SESSION_QUERY_INVALID_CONFIG'
    assert caught.value.message=='session-search SQLite config: '+key+' must be a positive safe integer'


def test_current_defaults_and_retired_concurrency_option():
    config=resolve_config(dict(path=':memory:',persistedInspectConcurrency=99))
    assert config['persistedReadConcurrency']==4 and config['preparedSessionCacheSize']==5
    assert 'persistedInspectConcurrency' not in config


@pytest.mark.parametrize('key',['persisted_read_concurrency','prepared_session_cache_size'])
@pytest.mark.parametrize('value',[False,0,1.5,float('inf')])
def test_current_abstract_query_config(key,value):
    with pytest.raises(SessionQueryError) as caught:CurrentSessionQueryService(None,**{key:value})
    assert caught.value.code=='SESSION_QUERY_INVALID_CONFIG'


@pytest.mark.asyncio
async def test_query_service_reuses_observation_reader_and_invalidates_revision(tmp_path,monkeypatch):
    ctx=Context();await ctx.plugin(CurrentSessionPlugin)
    await ctx.plugin(CurrentJsonlSessionPersistencePlugin,dict(root=str(tmp_path/'logs'),compression='none'))
    p=ctx.get('sessionPersistence');h=await p.create(dict(version=3,id='cold',createdAt=1,isSeeded=False));await h.flush();await h.close()
    query=CurrentSessionQueryService(ctx);calls=[];original=p.open
    async def opened(*args,**kwargs):calls.append(args);return await original(*args,**kwargs)
    monkeypatch.setattr(p,'open',opened)
    try:
        first=await query.observeSession('cold');second=await query.observeSession('cold')
        assert first.events is second.events and len(calls)==1
        writer=await p.open('cold','write');await writer.append([dict(type='turn/start',seq=0,time=1,data=dict(turn=1))]);await writer.close()
        third=await query.observeSession('cold')
        assert len(first.events)==0 and len(third.events)==2 and third.events is not first.events
        for lease in (first,second,third):lease.dispose()
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_current_corpus_batch_read_concurrency_settlement_order_and_handle_cleanup():
    entries={str(i):dict(version=3,id=str(i),createdAt=1,isSeeded=False) for i in range(5)}
    active=0;maximum=0;closed=[];release=asyncio.Event();entered=asyncio.Event()
    async def listing(options=None):return [dict(header=header,revision='r1') for header in entries.values()]
    async def opened(sid,access,options=None):
        assert access=='read'
        async def read(**kwargs):
            nonlocal active,maximum
            active+=1;maximum=max(maximum,active)
            if active==2:entered.set()
            try:await release.wait();return dict(eventState='detached',events=[])
            finally:active-=1
        async def close():closed.append(sid)
        return SimpleNamespace(header=entries[sid],inheritedEventCount=0,read=read,close=close)
    ctx=SimpleNamespace(services={})
    ctx.get=lambda key:ctx.services.get(key)
    ctx.services.update(sessions=SimpleNamespace(get=lambda sid:None),sessionPersistence=SimpleNamespace(list=listing,open=opened))
    corpus=CurrentSessionCorpus(ctx,2)
    def project(source):
        if source['header'].id=='1':raise ValueError('projection failed')
        return source['header'].id
    task=asyncio.create_task(corpus.project_many(['4','0','1','2','3','4'],project))
    await asyncio.wait_for(entered.wait(),2);assert maximum==2;release.set()
    results=await task
    assert [row['sessionId'] for row in results]==['4','0','1','2','3']
    assert [row['status'] for row in results]==['fulfilled','fulfilled','rejected','fulfilled','fulfilled']
    assert sorted(closed)==['0','1','2','3','4'] and maximum==2


def test_reconciliation_metadata_compatibility_ignores_version_and_origin_but_checks_agent_preset():
    old=dict(version=0,id='same',createdAt=1,isSeeded=False,origin='before')
    new=dict(old,version=3,origin='after')
    def snapshot(header):return dict(same=dict(header=header,revision='same-token'))
    assert same_snapshots(snapshot(old),snapshot(new))
    assert not same_snapshots(snapshot(old),snapshot(dict(new,agentPreset='changed')))


@pytest.mark.asyncio
async def test_index_header_is_current_even_when_index_contains_historical_version():
    ctx=Context();await ctx.plugin(CurrentSessionPlugin)
    query=CurrentSqliteSessionQueryEngine(ctx,dict(path=':memory:',openAt='never'))
    try:
        row=dict(session_id='same',version=0,created_at=1,cwd=None,parent_session=None,seed_length=None,delegation_depth=None,agent_preset=None)
        assert query._row_header(row).version==3
    finally:await query.close();await ctx.fiber.dispose()
