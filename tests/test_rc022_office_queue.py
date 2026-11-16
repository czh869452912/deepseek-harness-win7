import asyncio

import pytest
import pytest_asyncio

from dsh.core.abort import AbortController
from dsh.office.errors import OfficeKitError
from dsh.office.queue import ConversionQueue

OUTPUT=dict(kind='pdf',pdf=bytearray(b'%PDF'),missingFonts=['Font'])


@pytest_asyncio.fixture
async def harness():
    owned=[];gates=[];requests=[]
    def make(**config):
        state=dict(reads=[],converts=[]);entered=asyncio.Event();gate=asyncio.Event();gates.append(gate)
        async def convert(data,request,signal):
            state['converts'].append((bytes(data),request['operation']));entered.set()
            if config.pop('block',False):await gate.wait()
            return OUTPUT
        queue=ConversionQueue({key:value for key,value in config.items() if key!='block'},'test',convert);owned.append(queue)
        original=queue.read
        def read(*args):value=original(*args);requests.append(value);return value
        queue.read=read
        def source(key,byte=1,priority='foreground',size=1,version='v1',read_version='v1',operation=None):
            async def read(signal,maximum):state['reads'].append((key,maximum));return dict(bytes=bytes([byte]),version=read_version)
            source=dict(key=key,version=version,read=read)
            if size is not None:source['bytes']=size
            return dict(extension='docx',priority=priority,operation=operation or dict(kind='pdf'),source=source)
        return queue,state,source,entered,gate
    yield make
    for gate in gates:gate.set()
    await asyncio.gather(*(queue.dispose() for queue in owned),return_exceptions=True)
    await asyncio.gather(*requests,return_exceptions=True)


@pytest.mark.asyncio
async def test_metadata_content_sharing_aliases_and_independent_results(harness):
    queue,state,source,entered,gate=harness(block=True);a=source('a');b=source('b')
    first=queue.read(a);await entered.wait();same=queue.read(a);equal=queue.read(b)
    while len(state['reads'])<2:await asyncio.sleep(0)
    assert len(state['converts'])==1;gate.set();one,two,three=await asyncio.gather(first,same,equal)
    assert len({row['cacheKey'] for row in (one,two,three)})==1
    one['pdf'][0]=0;one['missingFonts'].clear();assert two['pdf']==b'%PDF' and three['missingFonts']==['Font']
    assert (await queue.read(b))['missingFonts']==['Font'] and len(state['reads'])==2


@pytest.mark.asyncio
async def test_foreground_promotes_queued_speculation_then_demotion_unblocks(harness):
    queue,state,source,entered,gate=harness(block=True,maxConcurrentConversions=1)
    active=queue.read(source('active'));await entered.wait();a=queue.read(source('a',2,'background'));b=queue.read(source('b',3,'background'))
    foreground=queue.read(source('b',3));assert [key for key,_ in state['reads']]==['active']
    gate.set();await asyncio.gather(active,a,b,foreground);assert [key for key,_ in state['reads']]==['active','b','a']


@pytest.mark.asyncio
async def test_foreground_evicts_metadata_queue_and_refuses_background_overflow(harness):
    queue,state,source,entered,gate=harness(block=True,maxConcurrentConversions=1,maxQueuedJobs=1)
    first=queue.read(source('active'));await entered.wait();discarded=queue.read(source('prewarm',2,'background'))
    with pytest.raises(OfficeKitError) as error:await queue.read(source('overflow',4,'background'))
    assert error.value.code=='busy';next_read=queue.read(source('requested',3))
    with pytest.raises(OfficeKitError) as error:await discarded
    assert error.value.code=='busy'
    with pytest.raises(OfficeKitError):await queue.read(source('overflow',4))
    gate.set();await asyncio.gather(first,next_read);assert [key for key,_ in state['reads']]==['active','requested']


@pytest.mark.asyncio
async def test_cancelled_work_holds_reservation_until_engine_cleanup(harness):
    queue,state,source,entered,gate=harness(block=True,maxConcurrentConversions=2,maxSourceBytes=1,maxInputBytes=1)
    controller=AbortController();failure=RuntimeError('cancelled');first=queue.read(source('active'),controller.signal);await entered.wait();later=queue.read(source('later',2))
    controller.abort(failure)
    with pytest.raises(RuntimeError) as error:await first
    assert error.value is failure and queue.sourceBytes==1 and [key for key,_ in state['reads']]==['active']
    gate.set();await later;await queue.dispose();assert queue.sourceBytes==0 and not queue.tasks


@pytest.mark.asyncio
async def test_shared_reader_cancellation_releases_source_index_and_reopens(harness):
    queue,state,source,entered,gate=harness(block=True);controller=AbortController();failure=RuntimeError('cancel')
    first=queue.read(source('a'),controller.signal);await entered.wait();other=queue.read(source('b'))
    while len(state['reads'])<2 or queue.running>1:await asyncio.sleep(0)
    controller.abort(failure)
    with pytest.raises(RuntimeError) as error:await first
    assert error.value is failure
    reopen=queue.read(source('a'))
    while len(state['reads'])<3:await asyncio.sleep(0)
    assert len(state['converts'])==1;gate.set();await asyncio.gather(other,reopen)
    assert (await queue.read(source('a')))['pdf']==b'%PDF' and len(state['reads'])==3


@pytest.mark.asyncio
async def test_reader_slot_foreground_reserve_and_cached_hit_before_limits(harness):
    queue,state,source,entered,gate=harness(maxReaders=2)
    cached=source('cached',9);await queue.read(cached)
    signal=AbortController();block=asyncio.Event()
    async def convert(data,request,lifetime):entered.set();await block.wait();return OUTPUT
    queue.convert=convert
    one=queue.read(source('one'),signal.signal)
    with pytest.raises(OfficeKitError):await queue.read(source('background',2,'background'))
    two=queue.read(source('two',2));assert (await queue.read(cached))['pdf']==b'%PDF'
    with pytest.raises(OfficeKitError):await queue.read(source('three',3))
    block.set();await asyncio.gather(one,two)


@pytest.mark.asyncio
@pytest.mark.parametrize('case,code',[('version','source-changed'),('reserved','input-too-large'),('known','input-too-large')])
async def test_invalid_source_does_not_convert_or_cache(harness,case,code):
    queue,state,source,_,_=harness(maxInputBytes=1,maxSourceBytes=1)
    request=source('source',size=2 if case=='known' else 0 if case=='reserved' else 1,read_version='new' if case=='version' else 'v1')
    if case=='reserved':
        async def read(*_):return dict(bytes=b'ab',version='v1')
        request['source']['read']=read
    with pytest.raises(OfficeKitError) as error:await queue.read(request)
    assert error.value.code==code and not state['converts'] and not queue.ready


@pytest.mark.asyncio
async def test_unknown_size_reserves_entire_input_budget_and_zero_reserves_one(harness):
    queue,state,source,_,_=harness(maxInputBytes=5,maxSourceBytes=5)
    await queue.read(source('unknown',size=None));await queue.read(source('zero',size=0))
    assert state['reads']==[('unknown',5),('zero',1)]


@pytest.mark.asyncio
async def test_lru_and_alias_caps_independent_with_oversize_nonretention(harness):
    queue,state,source,_,_=harness(maxCachedEntries=2,maxSourceEntries=1)
    a,b,c=source('a',1),source('b',2),source('c',3)
    await queue.read(a);await queue.read(b);await queue.read(a);await queue.read(c)
    assert len(queue.ready)==2 and len(queue.aliases)==1
    before=len(state['converts']);await queue.read(b);assert len(state['converts'])==before+1
    queue2,state2,source2,_,_=harness(maxCachedBytes=1)
    await queue2.read(source2('a'));await queue2.read(source2('a'));assert len(state2['converts'])==2 and not queue2.ready


@pytest.mark.asyncio
async def test_background_disabled_still_allows_ready_alias_and_rejects_join(harness):
    queue,state,source,entered,gate=harness(maxBackgroundConversions=0,block=True)
    request=source('a');first=queue.read(request);await entered.wait()
    with pytest.raises(OfficeKitError):await queue.read(dict(request,priority='background'))
    gate.set();await first;assert (await queue.read(dict(request,priority='background')))['pdf']==b'%PDF'


@pytest.mark.asyncio
async def test_dispose_rejects_as_unavailable_and_waits_actual_work(harness):
    queue,state,source,entered,gate=harness(block=True);controller=AbortController();first=queue.read(source('active'),controller.signal);await entered.wait()
    disposal=queue.dispose()
    with pytest.raises(OfficeKitError) as error:await first
    assert error.value.code=='unavailable' and not controller.signal.aborted and not disposal.task.done()
    with pytest.raises(OfficeKitError) as error:await queue.read(source('new'))
    assert error.value.code=='unavailable';gate.set();await disposal;assert not queue.ready and not queue.tasks


@pytest.mark.asyncio
async def test_cancelled_python_waiter_keeps_explicit_signal_owned_reader(harness):
    queue,state,source,entered,gate=harness(block=True);owned=queue.read(source('active'))
    async def wait():return await owned
    waiter=asyncio.create_task(wait());await entered.wait();waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    assert queue.readers==1;gate.set();assert (await owned)['pdf']==b'%PDF'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind',['file','images'])
async def test_operation_specific_cache_and_deep_mutable_output_copies(harness,kind):
    queue,state,source,_,_=harness()
    async def convert(data,request,signal):
        if kind=='file':return dict(kind='file',data=bytearray(b'file'),missingFonts=['Font'],pageCount=1)
        return dict(kind='images',images=[dict(png=bytearray(b'png'),width=2,height=3,page=1)],pageCount=1,dpi=96,missingFonts=['Font'])
    queue.convert=convert;request=source('a',operation=dict(kind='convert',format='txt') if kind=='file' else dict(kind='images',maxBytes=10))
    one=await queue.read(request)
    (one['data'] if kind=='file' else one['images'][0]['png'])[0]=0;one['missingFonts'].clear()
    two=await queue.read(request);assert two['missingFonts']==['Font']
    assert (two['data'] if kind=='file' else two['images'][0]['png'])==(b'file' if kind=='file' else b'png')


@pytest.mark.asyncio
async def test_synchronous_abort_replacement_remains_shareable_after_old_work_finishes(harness):
    queue,state,source,_,_=harness(maxConcurrentConversions=2);first_entered=asyncio.Event();replacement_entered=asyncio.Event();first_done=asyncio.Event();replacement_done=asyncio.Event();pending=[]
    request=source('a');caller=AbortController();calls=[]
    async def convert(data,request,signal):
        calls.append(bytes(data));number=len(calls)
        if number==1:
            signal.addEventListener('abort',lambda _:pending.append(queue.read(request_original)))
            first_entered.set();await first_done.wait()
        if number==2:replacement_entered.set();await replacement_done.wait()
        return OUTPUT
    request_original=request;queue.convert=convert;first=queue.read(request,caller.signal)
    try:
        await first_entered.wait();caller.abort('reader left')
        with pytest.raises(RuntimeError) as error:await first
        assert error.value.cause=='reader left';await replacement_entered.wait();next_read=queue.read(source('next',2));first_done.set();await next_read
        same=queue.read(request);alias=queue.read(source('alias',1,'background'))
        while len(state['reads'])<4:await asyncio.sleep(0)
        assert [key for key,_ in state['reads']].count('a')==2 and len(calls)==3
        replacement_done.set();results=await asyncio.gather(pending[0],same,alias)
        assert len({row['cacheKey'] for row in results})==1
    finally:first_done.set();replacement_done.set();await asyncio.gather(*pending,return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_blocker',[False,True])
async def test_foreground_waiting_for_bytes_blocks_speculation_until_it_leaves(harness,cancel_blocker):
    queue,state,source,entered,gate=harness(block=True,maxInputBytes=50,maxSourceBytes=60,maxConcurrentConversions=2)
    first=queue.read(source('active',size=15));await entered.wait();caller=AbortController()
    foreground=queue.read(source('foreground',2,size=48),caller.signal);background=queue.read(source('background',3,'background',size=45))
    assert [key for key,_ in state['reads']]==['active']
    if cancel_blocker:
        caller.abort()
        with pytest.raises(Exception):await foreground
        await background;assert [key for key,_ in state['reads']]==['active','background']
    gate.set();await first
    if not cancel_blocker:
        await asyncio.gather(foreground,background);assert [key for key,_ in state['reads']]==['active','foreground','background']


@pytest.mark.asyncio
async def test_python_cancelled_error_reason_and_failed_source_release_admission(harness):
    queue,state,source,_,_=harness();caller=AbortController();reason=asyncio.CancelledError();caller.abort(reason)
    with pytest.raises(asyncio.CancelledError) as error:await queue.read(source('a'),caller.signal)
    assert error.value is reason
    request=source('a')
    async def read(*_):raise reason
    request['source']['read']=read
    with pytest.raises(asyncio.CancelledError) as error:await queue.read(request)
    assert isinstance(error.value,asyncio.CancelledError)
    await queue.dispose();assert queue.readers==0 and queue.sourceBytes==0 and not queue.tasks
