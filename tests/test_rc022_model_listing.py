import asyncio
import json
import threading

import pytest

from dsh.core.abort import AbortController
from dsh.llm.model_listing import parseModelListing, requestModelListing
from scripts import rc022_listing_http_probe as http_corpus
from scripts import rc022_model_listing_probe as decoder_corpus


@pytest.mark.asyncio
async def test_model_listing_decoder_boundary_corpus(tmp_path):
    rows=await decoder_corpus.observe()
    (tmp_path/'model-listing-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==1431
    assert rows[6]['value']['entries'][0]['capabilities']==dict(usable=True,facts=dict(inputModalities=['text']))
    assert rows[7]['value']['skipped']==3
    assert all(row.get('code')=='INVALID_RESPONSE' for row in rows[:6])
    assert any(row.get('value',{}).get('entries',[{}])[0].get('badge',{}).get('kind')=='invalid' for row in rows if row['kind']=='body')


@pytest.mark.asyncio
async def test_actual_model_listing_http_contract_and_workers(tmp_path):
    before={thread.ident for thread in threading.enumerate()}
    rows=await http_corpus.observe()
    (tmp_path/'listing-http-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    by_name={row['name']:row for row in rows}
    assert by_name['success']['value']['entries'][0]['id']=='a'
    assert by_name['override']['requests'][0]['accept']=='custom/type'
    assert by_name['case-append']['requests'][0]['accept']=='application/json, custom/type'
    assert by_name['status']['status']==401 and by_name['status']['code']=='HTTP_401'
    assert all(by_name[key]['value']==by_name['success']['value'] for key in ('gzip','deflate','deflate-raw','broken-gzip'))
    assert by_name['redirect']['code']=='TRANSPORT' and len(by_name['redirect']['requests'])==1
    assert all(by_name[key]['code']=='TIMEOUT' for key in ('header-timeout','body-timeout'))
    assert by_name['abort']['code']=='ABORTED' and by_name['pre-abort']['requests']==[]
    assert not any(thread.ident not in before and thread.name in ('listing-http-probe','dsh-http-cancellation') for thread in threading.enumerate())


@pytest.mark.asyncio
async def test_task_cancellation_joins_request_worker(monkeypatch):
    import contextlib
    import dsh.llm.model_listing as module
    entered,finished=threading.Event(),threading.Event()
    @contextlib.contextmanager
    def blocked(request,signal,**options):
        entered.set()
        try:
            while not signal.aborted:
                threading.Event().wait(.005)
            raise RuntimeError('cancelled read')
            yield
        finally: finished.set()
    monkeypatch.setattr(module,'open_stream',blocked)
    parent=AbortController()
    task=asyncio.create_task(requestModelListing('http://example.invalid/models',{},parent.signal))
    while not entered.is_set(): await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(task,1)
    assert finished.is_set() and not parent.signal.aborted and not parent.signal._listeners
