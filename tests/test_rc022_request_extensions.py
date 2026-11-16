import asyncio
import json

import pytest

from dsh.core.abort import AbortController
from dsh.cordis.context import Context
from dsh.llm.deepseek_api_extensions_current import CurrentDeepSeekLlmApiExtensions
from scripts import rc022_request_extensions_probe as corpus


@pytest.mark.asyncio
async def test_request_transactions_and_actual_registry_corpus(tmp_path):
    rows=await corpus.observe()
    (tmp_path/'request-extensions-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==48
    rounds=[row for row in rows if row.get('kind')=='registry']
    assert all(len(row['warnings'])==1 for row in rounds)
    assert [row['commits'] for row in rounds]==[1,2,3,4,5]
    assert 'inventory_bad' in json.loads(rounds[3]['payload'])
    assert all('inventory_bad' not in json.loads(row['payload']) for row in rounds if row['round']!=3)
    assert rows[-1]['unaccepted']==['DeepSeek LLM API extension acceptance failed [first commit; second commit]']*2


@pytest.mark.asyncio
async def test_cancelling_acceptance_waiter_preserves_the_shared_commit():
    ctx=Context();entered=asyncio.Event();release=asyncio.Event();calls=[]
    try:
        await ctx.plugin(CurrentDeepSeekLlmApiExtensions)
        async def commit():
            calls.append('started');entered.set();await release.wait();calls.append('done')
        ctx.deepseekLlmApiExtensions.register('inventory',dict(prepare=lambda _:dict(value=[1],accept=commit)))
        prepared=await ctx.deepseekLlmApiExtensions.prepare(dict(body={},signal=AbortController().signal))
        acceptance=prepared.accept()
        assert prepared.accept() is acceptance
        waiter=asyncio.ensure_future(acceptance);await entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):await waiter
        assert not acceptance.task.cancelled()
        release.set();await prepared.accept()
        assert calls==['started','done']
    finally:
        release.set()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_abandoned_preparation_settles_without_warning_or_late_commit():
    ctx=Context();entered=asyncio.Event();release=asyncio.Event();settled=asyncio.Event()
    try:
        await ctx.plugin(CurrentDeepSeekLlmApiExtensions)
        async def prepare(_):
            try:
                entered.set();await release.wait();raise RuntimeError('late rejected preparation')
            finally:settled.set()
        ctx.deepseekLlmApiExtensions.register('inventory',dict(prepare=prepare))
        controller=AbortController();reason=RuntimeError('caller disposed')
        pending=asyncio.ensure_future(ctx.deepseekLlmApiExtensions.prepare(dict(body={},signal=controller.signal)))
        await entered.wait();controller.abort(reason)
        with pytest.raises(RuntimeError) as raised:await pending
        assert raised.value is reason
        release.set();await settled.wait();await asyncio.sleep(0)
        assert not [message for message in ctx.logger.buffer if message.type=='warn']
    finally:
        release.set();await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_clone_failures_are_omitted_and_field_names_use_js_trim():
    ctx=Context()
    try:
        await ctx.plugin(CurrentDeepSeekLlmApiExtensions)
        registry=ctx.deepseekLlmApiExtensions
        cycle={};cycle['self']=cycle
        registry.register('cycle',dict(prepare=lambda _:dict(value=cycle)))
        registry.register('uncloneable',dict(prepare=lambda _:dict(value=lambda:None)))
        registry.register('\u0085',dict(prepare=lambda _:dict(value=['valid field'])))
        with pytest.raises(ValueError):registry.register('\ufeff',dict(prepare=lambda _:None))
        for _ in range(2):
            prepared=await registry.prepare(dict(body={},signal=AbortController().signal))
            assert dict(prepared.fields)=={'\u0085':['valid field']}
            await prepared.accept()
        assert len([message for message in ctx.logger.buffer if message.type=='warn'])==2
    finally:await ctx.fiber.dispose()
