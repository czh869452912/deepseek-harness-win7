import asyncio
import pytest

from dsh.cordis import Context
from dsh.code_runtime.ptc import PythonPtcRuntime


@pytest.mark.asyncio
async def test_real_runtime_directory_timeouts_bindings_and_disposal(tmp_path):
    from scripts import rc022_ptc_runtime_probe as probe
    probe.WORKSPACE = tmp_path
    rows = await asyncio.wait_for(probe.observe(), 30)
    indexed = {row['kind']: row for row in rows}
    assert indexed['json']['result'] == dict(logs=['ready'], value=dict(n=42))
    assert indexed['cwd-env']['result']['value'] == [tmp_path.name, {}]
    assert indexed['binding']['result']['value'] == dict(value=42)
    assert indexed['typed-error']['result']['value'] == ['binding refused', 'fail']
    assert indexed['large-binding']['result']['value'] == 100000
    assert indexed['null']['result'] == dict(logs=[], value=None)
    for kind in ('fresh', 'syntax'):
        assert indexed[kind]['result']['error'] == 'exception'
    for kind in ('invalid-output', 'output-limit', 'timeout', 'abort'):
        assert indexed[kind]['result']['error'] == kind
    assert indexed['binding-abort'] == dict(kind='binding-abort', error='abort', callerOwned=True)
    assert indexed['dispose']['error'] == 'abort'
    assert indexed['late-run']['rejected'] and indexed['late-resolve']['rejected']


@pytest.mark.asyncio
async def test_resolved_spec_and_unsupported_authority_are_enforced(tmp_path):
    ctx = Context()
    await ctx.plugin(PythonPtcRuntime, dict(timeoutMs=8000, maxTimeoutMs=5000))
    runtime = ctx.get('ptcRuntime')
    try:
        assert ctx.get('codeRuntime') is None
        assert runtime.programFormat == 'function-body' and not runtime.retainsState
        assert runtime.sandboxMode is None
        assert runtime.timeout == dict(defaultMs=5000, maxMs=5000)
        assert 'does not confine' in runtime.executionInstructions
        for policy in (None, {}, dict(mode='danger-full-access'), dict(mode='read-only')):
            with pytest.raises(ValueError, match='unsupported without confinement'):
                runtime.resolve(dict(program='', bindings=[], sandboxPolicy=policy))
            with pytest.raises(ValueError, match='unsupported without confinement'):
                await runtime.run(dict(program='', bindings=[], cwd=str(tmp_path), timeoutMs=None, sandboxPolicy=policy))
        with pytest.raises(ValueError, match='cwd must be absolute'):
            runtime.resolve(dict(program='', bindings=[], cwd='relative'))
        for choice in ({}, dict(cwd=str(tmp_path)), dict(cwd='relative', timeoutMs=1),
                       dict(cwd=str(tmp_path), timeoutMs=5001), dict(cwd=str(tmp_path), timeoutMs=False)):
            with pytest.raises(ValueError, match='requires resolved'):
                await runtime.run(dict(program='return 1', bindings=[], **choice))
        # A no-deadline call runs beyond the numeric default while another call
        # still observes its own deadline; stateOwner never shares memory.
        owner = object()
        spec = runtime.resolve(dict(program='import asyncio\nawait asyncio.sleep(.15)\nreturn 42',
            bindings=[], cwd=str(tmp_path), timeoutMs=None, stateOwner=owner))
        expired = runtime.resolve(dict(program='while True:\n    pass', bindings=[], cwd=str(tmp_path), timeoutMs=60))
        success, failure = await asyncio.gather(runtime.run(spec), runtime.run(expired))
        assert success == dict(logs=[], value=42)
        assert failure['error']['kind'] == 'timeout'
        await runtime.release(owner)
        spec.update(program='return missing')
        assert (await runtime.run(spec))['error']['kind'] == 'exception'
    finally:
        await ctx.fiber.dispose()
