import asyncio
import copy
import hashlib
import os
import shutil
import zipfile

import pytest

from dsh.cordis.context import Context
from dsh.javascript import runtime as implementation
from dsh.javascript.runtime import JavaScriptParseError, JavaScriptRuntime, JavaScriptRuntimeError
from scripts.build_quickjs import verify_archive


BOOTSTRAP = '''
globalThis.args=__request.args;
let reason;
globalThis.phase=Object.freeze(title=>__emit(JSON.stringify({type:'phase',title})));
globalThis.log=Object.freeze(message=>__emit(JSON.stringify({type:'log',message})));
globalThis.__receive=message=>{if(message.type==='cancel'&&reason===undefined) reason=message.reason;};
globalThis.__drive=async promise=>{
  let result;
  try {
    if(reason!==undefined) throw 'cancelled';
    const value=await promise;
    if(reason!==undefined) throw 'cancelled';
    result={value:value===undefined?null:value,stopReason:'completed',agentsStarted:0};
  } catch(error) {
    result={value:null,stopReason:reason===undefined?'error':'cancelled',
      error:reason===undefined?String(error):'workflow run cancelled: '+reason,agentsStarted:0};
  }
  __emit(JSON.stringify({type:'terminal',result}));
};
'''


def request(body, **changes):
    value = dict(body=body, name='workflow:runtime-test', bootstrap=BOOTSTRAP,
                 args=dict(nested=dict(value=2)), timeoutMs=100)
    value.update(changes)
    return value


@pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')
@pytest.mark.asyncio
@pytest.mark.parametrize('body', ['return {value:await Promise.resolve(7)}', 'for(;;){}', 'throw new Error("not executed")'])
async def test_parser_compiles_without_executing(body):
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    try:
        runtime = ctx.get('jsRuntime')
        runtime.parse(body, 'workflow:parse-only')
        with pytest.raises(JavaScriptParseError):
            runtime.parse('return {', 'workflow:bad-parse')
    finally:
        await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')
@pytest.mark.asyncio
@pytest.mark.parametrize('body,expected', [
    ('const seed=3; const add=value=>value+seed; let total=0; for(let index=0;index<5;index++) total+=add(index); return {total}', dict(total=25)),
    ('return {value:await Promise.resolve(7).then(value=>value*3)}', dict(value=21)),
    ('return {argsRealm:args instanceof Object,hookRealm:phase instanceof Function,frozen:Object.isFrozen(phase),args:args}',
     dict(argsRealm=False,hookRealm=False,frozen=True,args=dict(nested=dict(value=2)))),
    ('return {text:"中文😀",regexp:/\\p{Letter}+/u.test("中文"),big:String(2n**80n)}',
     dict(text='中文😀',regexp=True,big=str(2 ** 80))),
    ('return "x".repeat(200000)', 'x' * 200000),
], ids=['closure-loop', 'promise-await', 'host-realm', 'unicode-language', 'large-result'])
async def test_actual_engine_executes_language_promises_and_two_realms(body, expected):
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    try:
        runtime = ctx.get('jsRuntime')
        initial = request(body)
        original = copy.deepcopy(initial)
        worker = await runtime.open(initial)
        assert not worker.result.done()
        await worker.send(dict(type='go'))
        assert await asyncio.wait_for(asyncio.shield(worker.result), 5) == dict(
            value=expected, stopReason='completed', agentsStarted=0)
        await worker.dispose()
        assert worker.process.returncode == 0
        assert worker.failure is None
        assert initial == original
        assert not runtime._workers
    finally:
        await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')
@pytest.mark.asyncio
async def test_startup_cancel_does_not_execute_body_and_disposal_is_shared():
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    try:
        events = []
        worker = await ctx.get('jsRuntime').open(request('phase("must not execute"); return 1'), events.append)
        await worker.cancel('already aborted')
        await worker.cancel('later reason')
        assert await asyncio.wait_for(asyncio.shield(worker.result), 5) == dict(value=None, stopReason='cancelled',
            error='workflow run cancelled: already aborted', agentsStarted=0)
        assert events == []
        assert worker.dispose() is worker.dispose()
        await worker.dispose()
        assert worker.process.returncode == 0
    finally:
        await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')
@pytest.mark.asyncio
async def test_initial_cpu_slice_is_interrupted_without_blocking_host_loop():
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    try:
        worker = await ctx.get('jsRuntime').open(request('for(;;){}'))
        await worker.send(dict(type='go'))
        await asyncio.sleep(0)
        try:
            result = await asyncio.wait_for(asyncio.shield(worker.result), 5)
        except JavaScriptRuntimeError as error:
            assert 'interrupted' in str(error)
        else:
            assert result['stopReason'] == 'error'
            assert 'interrupted' in result['error']
        await worker.dispose()
        assert worker.process.returncode is not None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')
@pytest.mark.asyncio
@pytest.mark.parametrize('body', ['await Promise.resolve(); for(;;){}', 'await new Promise(()=>{})'])
async def test_unsettled_async_body_is_physically_terminated_on_owner_unload(body):
    ctx = Context()
    fiber = await ctx.plugin(JavaScriptRuntime)
    runtime = ctx.get('jsRuntime')
    worker = await runtime.open(request(body), grace_ms=20)
    await worker.send(dict(type='go'))
    await asyncio.wait_for(fiber.dispose(), 5)
    assert worker.closed.done()
    assert worker.process.returncode is not None
    assert not runtime._workers
    assert ctx.get('jsRuntime') is None
    await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')
@pytest.mark.asyncio
async def test_cancel_during_spawn_waits_for_owned_process_cleanup(monkeypatch):
    ctx = Context()
    await ctx.plugin(JavaScriptRuntime)
    entered, release = asyncio.Event(), asyncio.Event()
    original = asyncio.create_subprocess_exec
    processes = []
    async def delayed_spawn(*arguments, **options):
        process = await original(*arguments, **options)
        processes.append(process)
        entered.set()
        await release.wait()
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed_spawn)
    try:
        opening = asyncio.create_task(ctx.get('jsRuntime').open(request('return 1')))
        await asyncio.wait_for(entered.wait(), 5)
        opening.cancel()
        await asyncio.sleep(0)
        assert not opening.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(opening, 5)
        assert len(processes) == 1 and processes[0].returncode is not None
        assert not ctx.get('jsRuntime')._workers
    finally:
        release.set()
        await ctx.fiber.dispose()


@pytest.mark.skipif(os.name != 'nt', reason='Private MSVCRT worker targets Windows')
@pytest.mark.asyncio
async def test_provider_unload_owns_late_spawn_and_refuses_new_work(monkeypatch):
    ctx = Context()
    fiber = await ctx.plugin(JavaScriptRuntime)
    runtime = ctx.get('jsRuntime')
    entered, release = asyncio.Event(), asyncio.Event()
    original = asyncio.create_subprocess_exec
    processes = []
    async def delayed_spawn(*arguments, **options):
        process = await original(*arguments, **options)
        processes.append(process)
        entered.set()
        await release.wait()
        return process
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed_spawn)
    opening = asyncio.create_task(runtime.open(request('return 1')))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        unloading = asyncio.ensure_future(fiber.dispose())
        while not runtime._closed:
            await asyncio.sleep(0)
        assert not unloading.done()
        with pytest.raises(JavaScriptRuntimeError, match='disposed'):
            await runtime.open(request('return 2'))
        with pytest.raises(JavaScriptRuntimeError, match='disposed'):
            runtime.parse('return 2', 'after-unload')
        release.set()
        with pytest.raises(JavaScriptRuntimeError, match='disposed'):
            await asyncio.wait_for(opening, 5)
        await asyncio.wait_for(unloading, 5)
        assert len(processes) == 1 and processes[0].returncode is not None
        assert not runtime._workers and not runtime._spawns
    finally:
        release.set()
        await asyncio.gather(opening, return_exceptions=True)
        await ctx.fiber.dispose()


@pytest.mark.parametrize('name', ['runtime.json', 'dsh_js_worker.exe', 'QUICKJS-NOTICES.txt', 'MinGW-COPYING.winpthreads.txt', 'build-provenance.json'])
def test_modified_private_resource_is_refused_before_execution(tmp_path, monkeypatch, name):
    resources = tmp_path / 'runtime'
    shutil.copytree(implementation.RESOURCE_ROOT, resources)
    target = resources / name
    target.write_bytes(target.read_bytes() + b'changed')
    monkeypatch.setattr(implementation, 'RESOURCE_ROOT', resources)
    with pytest.raises(JavaScriptRuntimeError, match='differ'):
        implementation.verify_resources()


def test_only_source_worker_temp_environment_is_forwarded(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'synthetic-unforwarded-key')
    monkeypatch.setenv('NODE_OPTIONS', '--synthetic-never-forwarded')
    assert set(implementation.worker_environment()).issubset({'TMP', 'TEMP'})


@pytest.mark.parametrize('damage', ['archive-bytes', 'extracted-bytes', 'extra-header', 'traversal', 'wrong-prefix'])
def test_build_refuses_unpinned_or_injected_archive_inputs(tmp_path, damage):
    source = tmp_path / 'source'
    source.mkdir()
    archive_path = tmp_path / 'source.zip'
    member = 'source/header.h'
    if damage == 'traversal':
        member = 'source/../escaped.h'
    elif damage == 'wrong-prefix':
        member = 'foreign/header.h'
    with zipfile.ZipFile(str(archive_path), 'w') as archive:
        archive.writestr(member, b'pinned header')
    expected = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (source / 'header.h').write_bytes(b'pinned header')
    if damage == 'archive-bytes':
        archive_path.write_bytes(archive_path.read_bytes() + b'changed')
    elif damage == 'extracted-bytes':
        (source / 'header.h').write_bytes(b'foreign header')
    elif damage == 'extra-header':
        (source / 'injected.h').write_bytes(b'unreviewed additional input')
    with pytest.raises(ValueError):
        verify_archive(archive_path, source, expected)
