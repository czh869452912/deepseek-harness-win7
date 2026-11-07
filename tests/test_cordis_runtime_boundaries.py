"""Definition atomicity, pinned Client parse acceptance, and an open timeout gap."""
import json
import hashlib
import asyncio
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.extensions.host_runner import DynamicCordisRunner
from dsh.javascript.client_syntax import precheck_client_body
from dsh.javascript.runtime import JavaScriptParseError, parse_javascript_body


REGEX_VALID_BODIES = [
    'const p = /a/ims; return ctx => {};',
    'const p = /(?<word>a)|(?<other>b)/; return ctx => {};',
    r'const p = /(?<word>a)\k<word>/u; return ctx => {};',
    'const p = /(?:a)(?=b)(?!c)(?<=a)(?<!c)/; return ctx => {};',
    r'const p = /\(\?i:a\)/; return ctx => {};',
    'const p = /[(?i:a)]/; return ctx => {};',
    'const text = "(?i:a) (?<word>a)|(?<word>b)"; return ctx => {};',
    'const text = `(?i:a) (?<word>a)|(?<word>b)`; return ctx => {};',
    '// /(?i:a)/ /(?<word>a)|(?<word>b)/\nreturn ctx => {};',
    'const p = new RegExp("(?i:a)"); return ctx => {};',
    'const p = RegExp("(?<word>a)|(?<word>b)"); return ctx => {};',
    r'const p = /(?<\u0077ord>a)|(?<other>b)/u; return ctx => {};',
    r'const p = /[\p{ASCII}&&\p{Letter}]/v; return ctx => {};',
    r'const p = /(?<word>a)/d; return ctx => {};',
]
REGEX_INVALID_BODIES = [
    'const p = /(?i:a)/; return ctx => {};',
    'const p = /(?<word>a)|(?<word>b)/; return ctx => {};',
    'const p = /(?im-s:a)/; return ctx => {};',
    'const p = /(?-i:a)/; return ctx => {};',
    'const p = /(?i:a)/u; return ctx => {};',
    'const p = /(?i:a)/v; return ctx => {};',
    'const p = /(?:(?<word>a)|(?:(?<word>b)|c))/; return ctx => {};',
    r'const p = /(?<word>a)|(?<\u0077ord>b)/u; return ctx => {};',
    'const p = /(?<word>a)(?<word>b)/; return ctx => {};',
    'const p = /(?<word>a)|(?<word>b)/v; return ctx => {};',
]


CLIENT_BODIES = [
    'return () => {}', 'await Promise.resolve(); return () => {}',
    'for (;;) {}', 'throw new Error("must not run during define")',
    'const constructed = new.target !== undefined; return ctx => {};',
    'const using = 1; return ctx => {};',
    'const text = "using resource = null"; return ctx => {};',
    'const text = `using resource = null`; return ctx => {};',
    '// using resource = null\nreturn ctx => {};',
    'const expression = /using resource = null/; return ctx => {};',
    'const object = { using: 1 }; return ctx => object.using;',
    'const using = value => value; using(1); return ctx => {};',
    'const using = Promise.resolve(1); await using; return ctx => {};',
    'return import("unused-client-module", {with: {type: "json"}});',
    *REGEX_VALID_BODIES,
    'return {', 'return () => {', 'const x: number = 1; return () => {}',
    'return { value: 1 as const }', 'await;',
    'using resource = null; return ctx => {};',
    'await using resource = null; return ctx => {};',
    'for (using item of []) {} return ctx => {};',
    *REGEX_INVALID_BODIES,
]


@pytest.mark.asyncio
@pytest.mark.parametrize('with_host', [False, True], ids=['client-only', 'dual-half'])
async def test_client_precheck_matches_pinned_function_gate_and_keeps_registry_atomic(tmp_path, with_host):
    # Exactly the compile-only gate used by pinned sandbox.precheckCode.
    probe = """const codes=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const accepted=codes.map(code=>{try{new Function('(async () => {\\n'+code+'\\n})()');return true}catch(e){if(e.name!=='SyntaxError')throw e;return false}});
(async()=>{const plugin=await new Function('return (async () => {\\n'+codes[4]+'\\n})()')();
console.log(JSON.stringify({node:process.version, accepted, evaluatedPluginType:typeof plugin}));})().catch(error=>{console.error(error);process.exitCode=1});"""
    script = tmp_path / 'source-client-precheck.cjs'
    script.write_text(probe, encoding='utf-8')
    completed = subprocess.run(['node', str(script)], input=json.dumps(CLIENT_BODIES),
                               cwd=str(Path(__file__).resolve().parents[1]),
                               capture_output=True, encoding='utf-8', check=True)
    source_observation = json.loads(completed.stdout)
    expected = source_observation['accepted']
    assert source_observation['evaluatedPluginType'] == 'function'
    assert expected == [True] * (14 + len(REGEX_VALID_BODIES)) + [False] * (8 + len(REGEX_INVALID_BODIES))
    print(json.dumps(dict(bodies=CLIENT_BODIES, source_acceptance=expected,
                         node=source_observation['node'])))
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner)
    runner = ctx.get('dynamicCordisRunner')
    try:
        created = None
        for body, accepted in zip(CLIENT_BODIES, expected):
            for existing in [False, True] if created else [False]:
                before, ids = runner.inventory(), dict(runner._next_ids)
                code = dict(client=body)
                if with_host:
                    code['host'] = 'def plugin(ctx):\n    pass\n'
                request = dict(sessionId='owner', plugin=dict(kind='existing', pluginId=created['pluginId'])
                    if existing else dict(kind='new', idPrefix='parse'), name='Client', purpose='parse only',
                    code=code)
                if accepted:
                    created = runner.define(request)
                else:
                    with pytest.raises(ValueError, match='code.client.*failed to parse') as failure:
                        runner.define(request)
                    assert 'SyntaxError' in str(failure.value)
                    assert runner.inventory() == before
                    assert runner._next_ids == ids
    finally:
        await ctx.fiber.dispose()


def test_client_context_does_not_change_shared_workflow_parse_semantics():
    source = 'const constructed = new.target !== undefined; return ctx => {};'
    with pytest.raises(JavaScriptParseError, match='new.target'):
        parse_javascript_body(source, 'workflow-context-control')
    precheck_client_body(source)


def test_client_parser_needs_no_installed_node(monkeypatch):
    monkeypatch.setenv('PATH', '')
    precheck_client_body('const constructed = new.target !== undefined; return ctx => {};')


@pytest.mark.parametrize('architecture', ['x64', 'x86'])
def test_client_syntax_gate_on_both_shipped_worker_architectures(monkeypatch, architecture):
    from dsh.javascript import client_syntax, runtime
    directory = Path(runtime.__file__).with_name('bin')
    if architecture == 'x86':
        directory = directory / 'x86'
    binary = directory / 'dsh_js_worker.exe'
    identity = json.loads((directory / 'runtime.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == identity['binary_sha256']
    monkeypatch.setattr(client_syntax, 'verify_resources', lambda: binary)
    precheck_client_body('const constructed = new.target !== undefined; return ctx => {};')
    with pytest.raises(JavaScriptParseError, match='code.client:1:7'):
        precheck_client_body('using resource = null; return ctx => {};')
    for body in REGEX_VALID_BODIES:
        precheck_client_body(body)
    for body in REGEX_INVALID_BODIES:
        with pytest.raises(JavaScriptParseError, match=r'(?s)code.client:1:.*Invalid regular expression'):
            precheck_client_body(body)


@pytest.mark.asyncio
async def test_initial_native_blocking_evaluation_respects_vm_timeout():
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner, dict(vmTimeoutMs=5))
    runner = ctx.get('dynamicCordisRunner')
    owner = SimpleNamespace(id='owner', steer=lambda _: None)
    try:
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='block'),
            name='Native blocking', purpose='initial synchronous timeout boundary',
            code=dict(host='import time\ntime.sleep(0.08)\ndef plugin(ctx):\n    pass\n')))
        start = time.monotonic()
        result = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
        elapsed = time.monotonic() - start
        print(json.dumps(dict(vmTimeoutMs=5, blockingMs=80, elapsedMs=elapsed * 1000, result=result)))
        assert not result['ok'] and 'vmTimeoutMs' in result['message']
        # Distinguish hard interruption from waiting for the 80ms native call.
        assert elapsed < 0.06
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('blocking', ['import time\ntime.sleep(0.6)', 'sum(range(10 ** 12))', 'while True:\n    pass',
    "harness.defineTool({'name': 'large', 'description': 'large', 'parameters': {str(i): {'type': 'string'} for i in range(50000)}, "
    "'output': {'schema': {'type': 'json'}, 'render': lambda args, value: []}, 'execute': lambda args, execution: None})"],
                         ids=['native-sleep', 'native-compute', 'python-loop', 'initial-tool-dsl'])
async def test_timeout_kills_host_without_late_effects_or_blocking_parent(tmp_path, blocking):
    ctx = Context()
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(ToolsPlugin())
    await ctx.plugin(DynamicCordisRunner, dict(vmTimeoutMs=30))
    runner = ctx.get('dynamicCordisRunner')
    owner = SimpleNamespace(id='owner', steer=lambda _: None)
    marker = tmp_path / 'must-not-appear.txt'
    process = runner._spare.process
    heartbeat = asyncio.create_task(asyncio.sleep(.01))
    try:
        source = ("harness.handle('partial', lambda args: args)\n" + blocking +
                  '\nopen(' + repr(str(marker)) + ", 'w', encoding='utf-8').write('late')\ndef plugin(ctx):\n    pass\n")
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='bound'),
            name='Hard boundary', purpose='No surviving evaluator', code=dict(host=source)))
        start = time.monotonic()
        result = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
        elapsed = time.monotonic() - start
        assert not result['ok'] and 'vmTimeoutMs' in result['message'], result
        assert elapsed < .4
        assert heartbeat.done()
        assert process.poll() is not None
        assert 'activeRun' not in runner.inventory()[0]
        assert not runner._host_processes
        await asyncio.sleep(.65)
        assert not marker.exists()
        print(json.dumps(dict(blocking=blocking, elapsedMs=elapsed * 1000, processExit=process.returncode)))
    finally:
        await heartbeat
        await ctx.fiber.dispose()
