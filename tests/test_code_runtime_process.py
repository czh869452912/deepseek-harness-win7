import asyncio
import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.code_runtime.process import PythonProcessRuntime


@pytest.mark.asyncio
async def test_real_worker_async_bindings_typed_errors_json_and_isolation():
    ctx = Context()
    fiber = await ctx.plugin(PythonProcessRuntime)
    runtime = ctx.get('codeRuntime')
    async def twice(value):
        await asyncio.sleep(.03)
        return {'value': value['n'] * 2}
    async def fail(value):
        raise ValueError('binding refused')
    bindings = [{'global': 'tools', 'functions': {'twice': twice, '__proto__': twice, 'fail': fail},
                 'errorClass': {'name': 'ToolError', 'memberNameProperty': 'member'}}]
    program = "result = await tools.twice({'n': 21})\nprint('hello')\ntry:\n    await tools.fail({})\nexcept ToolError as error:\n    result['error'] = [str(error), error.member]\nreturn result"
    try:
        result = await runtime.run(dict(program=program, bindings=bindings))
        assert result == dict(logs=['hello'], value=dict(value=42, error=['binding refused', 'fail']))
        assert runtime.language == 'python' and runtime.isolation == 'process'
        result = await runtime.run(dict(program="return await tools['__proto__']({'n': 2})", bindings=bindings))
        assert result['value'] == {'value': 4}
        result = await runtime.run(dict(program='import os\nreturn dict(os.environ)', bindings=[]))
        assert result['value'] == {}
        result = await runtime.run(dict(program='return result', bindings=[]))
        assert result['error']['kind'] == 'exception'
        result = await runtime.run(dict(program='return {1, 2}', bindings=[]))
        assert result['error']['kind'] == 'invalid-output'
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_hot_loop_compute_budget_slow_binding_exclusion_and_abort():
    ctx = Context()
    fiber = await ctx.plugin(PythonProcessRuntime, dict(computeMs=200, maxWallMs=5000))
    runtime = ctx.get('codeRuntime')
    started, settled = asyncio.Event(), asyncio.Event()
    async def slow(value):
        started.set()
        await asyncio.sleep(.6)
        settled.set()
        return 'slow result'
    bindings = [{'global': 'tools', 'functions': {'slow': slow}}]
    try:
        result = await runtime.run(dict(program='return await tools.slow({})', bindings=bindings))
        assert result.get('value') == 'slow result', result
        result = await runtime.run(dict(program='while True:\n    pass', bindings=[]))
        assert result['error'] == dict(kind='timeout', message='compute-time budget exceeded')
        started.clear()
        settled.clear()
        controller = AbortController()
        pending = asyncio.create_task(runtime.run(dict(program='return await tools.slow({})', bindings=bindings, signal=controller.signal)))
        await asyncio.wait_for(started.wait(), 3)
        controller.abort('stop')
        result = await asyncio.wait_for(pending, 2)
        assert result['error']['kind'] == 'abort'
        await asyncio.wait_for(settled.wait(), 2)
        pending = asyncio.create_task(runtime.run(dict(program='while True:\n    pass', bindings=[])))
        await asyncio.sleep(.05)
        await fiber.dispose()
        assert (await pending)['error']['kind'] == 'abort'
        with pytest.raises(RuntimeError, match='disposal'):
            await runtime.run(dict(program='return 1', bindings=[]))
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_outer_output_cap_does_not_cap_binding_result():
    ctx = Context()
    fiber = await ctx.plugin(PythonProcessRuntime, dict(maxOutputBytes=64))
    runtime = ctx.get('codeRuntime')
    try:
        result = await runtime.run(dict(program="value = await tools.large({})\nreturn len(value)",
            bindings=[{'global': 'tools', 'functions': {'large': lambda _: 'x' * 100000}}]))
        assert result == dict(logs=[], value=100000)
        result = await runtime.run(dict(program="print('x' * 1000)\nreturn 42", bindings=[]))
        assert result['error']['kind'] == 'output-limit'
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_memory_substrate_failure_and_unresolvable_promise_wall_budget():
    ctx = Context()
    fiber = await ctx.plugin(PythonProcessRuntime, dict(maxOldGenerationSizeMb=64, maxWallMs=1000))
    runtime = ctx.get('codeRuntime')
    try:
        result = await runtime.run(dict(program="value = bytearray(256 * 1024 * 1024)\nreturn len(value)", bindings=[]))
        assert result['error']['kind'] == 'worker-exit', result
        result = await runtime.run(dict(program='import asyncio\nawait asyncio.Future()', bindings=[]))
        assert result['error'] == dict(kind='timeout', message='wall-time budget exceeded')
    finally:
        await fiber.dispose()


@pytest.mark.asyncio
async def test_actual_ptc_tool_dispatch_uses_python_runtime():
    from dsh.core.tools import ToolsPlugin, ToolExecutionInput
    ctx = Context()
    await ctx.plugin(PythonProcessRuntime)
    await ctx.plugin(ToolsPlugin, {'mode': 'code'})
    tools = ctx.get('tools')
    tools.register(dict(name='double', description='Double a number',
        parameters={'type': 'object', 'properties': {'n': {'type': 'integer'}}, 'required': ['n']},
        execute=lambda args, execution: {'value': args['n'] * 2},
        output={'schema': {'type': 'object', 'properties': {'value': {'type': 'integer'}}, 'required': ['value']},
                'render': lambda args, value: [{'type': 'text', 'text': str(value['value'])}]}))
    try:
        result = await tools.execute(ToolExecutionInput('code-1', 'run_code',
            {'code': "answer = await tools.double({'n': 21})\nreturn answer", 'description': 'Execute real nested tool'},
            signal=AbortController().signal))
        assert not result.isError, result.content
        assert result.value == {'logs': [], 'result': {'value': 42}}
    finally:
        await ctx.fiber.dispose()
