import asyncio
import json

import pytest

from dsh.boot.config_graph_current import project_native_config
from dsh.cordis import Context
from dsh.cordis.schema import Schema
from dsh.javascript.runtime import JavaScriptRuntime
from scripts.rc022_config_graph_probe import observe, cases


@pytest.mark.asyncio
async def test_actual_live_schema_and_builder_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'config-graph-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==37
    lazy={row['case']['mode']:row for row in rows if row['case']['kind']=='lazy'}
    assert lazy['cached']['calls']==[]
    assert lazy['loose']['calls']==[]
    assert lazy['shared']['calls']==['builder']
    assert lazy['throw']['error']=='builder failed'
    assert lazy['cycle']['error']=='config: lazy cycle has no concrete schema'
    assert all('transform' not in row['calls'] for row in rows)


@pytest.mark.asyncio
async def test_builder_exception_identity_and_worker_release():
    ctx=Context();error=ValueError('exact builder error')
    def builder():raise error
    try:
        await ctx.plugin(JavaScriptRuntime)
        with pytest.raises(ValueError) as captured:
            await project_native_config(ctx,Schema.lazy(builder))
        assert captured.value is error
        assert not ctx.jsRuntime._workers
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancel_during_lazy_request_releases_worker():
    ctx=Context();tasks=[];workers=[]
    try:
        await ctx.plugin(JavaScriptRuntime)
        original=ctx.jsRuntime.open
        async def opening(*args,**kwargs):
            worker=await original(*args,**kwargs);workers.append(worker);return worker
        ctx.jsRuntime.open=opening
        def builder():
            tasks[0].cancel()
            return Schema.string()
        tasks.append(asyncio.create_task(project_native_config(ctx,Schema.lazy(builder))))
        with pytest.raises(asyncio.CancelledError):await tasks[0]
        assert workers and all(worker.process.returncode is not None for worker in workers)
        assert not ctx.jsRuntime._workers
        assert not workers[0].result.cancelled()
    finally:await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_opaque_callbacks_and_serialization_hooks_are_never_invoked():
    ctx=Context();calls=[]
    class Opaque:
        def toJSON(self):calls.append('toJSON');raise AssertionError('opaque hook')
    try:
        await ctx.plugin(JavaScriptRuntime)
        root=Schema.string();root.meta['default']=Opaque()
        value=await project_native_config(ctx,root)
        assert value['acceptsMissing']=='unknown'
        assert 'non-JSON object' in value['limitations'][0]
        assert not calls
        assert not ctx.jsRuntime._workers
    finally:await ctx.fiber.dispose()
