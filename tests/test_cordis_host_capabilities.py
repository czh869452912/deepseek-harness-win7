"""Default dynamic capability denial and supported Context alternatives."""

import pytest

from canonical_web_fixture import web_context, close_web_context


@pytest.mark.asyncio
@pytest.mark.parametrize('program', [
    "open('not-created.txt', 'w')", "__import__('os')", "import socket", "import subprocess",
    "import pathlib", "import threading", "import sys", "import importlib", "import builtins",
    'eval("open(\'not-created.txt\', \'w\')", {})', 'exec("import socket", {})',
    'eval(compile("__import__(\'os\')", "generated", "eval"), {})', "input()",
    "import asyncio\nasyncio.get_event_loop()", "import asyncio\nasyncio.run(None)",
    "import asyncio\nasyncio.create_subprocess_exec('cmd')",
    "from asyncio import get_event_loop", "from time import sleep",
    "import fractions\nfractions.sys", "import statistics\nstatistics.random",
    'license()',
], ids=['open', 'import-os', 'socket', 'subprocess', 'pathlib', 'threading', 'sys', 'importlib',
        'builtins', 'eval-open', 'exec-import', 'compiled-import', 'input', 'event-loop', 'asyncio-run', 'asyncio-process',
        'from-event-loop', 'native-sleep', 'fraction-module-leak', 'statistics-module-leak', 'license-reader'])
async def test_default_dynamic_host_denies_capability_bypasses(tmp_path, program):
    ctx = await web_context(tmp_path / 'home')
    try:
        await ctx.get('sessionController').create(dict(sessionId='limits', cwd=str(tmp_path), agentPreset='cordis'))
        owner, runner = ctx.get('agents').get('limits'), ctx.get('dynamicCordisRunner')
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='limit'),
            name='Denied entry', purpose='Context capability boundary',
            code=dict(host=program + '\ndef plugin(ctx):\n    pass\n')))
        result = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
        assert not result['ok'], result
        assert 'Context services' in result['message'] and 'cordis_inspect' in result['message']
        assert 'activeRun' not in runner.inventory()[0]
        assert not runner._host_processes
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_computation_modules_timer_and_real_filesystem_service(tmp_path):
    path = tmp_path / 'service-data.txt'
    path.write_text('中文 Win7', encoding='utf-8')
    ctx = await web_context(tmp_path / 'home')
    try:
        await ctx.get('sessionController').create(dict(sessionId='compute', cwd=str(tmp_path), agentPreset='cordis'))
        owner, runner = ctx.get('agents').get('compute'), ctx.get('dynamicCordisRunner')
        # Select the actual Python filesystem provider's published contract.
        fs = ctx.get('fs')
        assert fs is not None
        source = """import math, json, base64
from collections import Counter
from hashlib import sha256
from datetime import datetime
import asyncio
async def plugin(ctx):
    async def read(args):
        await asyncio.sleep(0)
        await ctx.timeout(2)
        text = await ctx.get('fs').readText(args['path'])
        generated = {}
        exec(compile('def add(a, b): return a + b', 'generated', 'exec'), generated)
        return {'root': math.sqrt(81), 'counter': dict(Counter('aba')), 'file': text,
                'json': json.loads(json.dumps(args)), 'text': base64.b64decode('V2luNw==').decode('utf-8'),
                'hash': sha256(b'Win7').hexdigest(), 'undefined': UNDEFINED is UNDEFINED,
                'date': datetime(2020, 1, 2).strftime('%Y-%m-%d'),
                'generated': generated['add'](20, 22), 'evaluated': eval('x + 2', {'x': 40}),
                'callback_total': callback_total}
    harness.handle('read', read)
    harness.handle('evaluate', eval)
    harness.handle('execute', exec)
plugin.inject = ['timer']
"""
        defined = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='comp'),
            name='Computation', purpose='Supported Python closure', code=dict(host=source)))
        result = await runner.run(owner, defined['pluginId'], defined['packageId'], 'run')
        assert result['ok'], result
        # Direct language helpers as callbacks must stay in the authored realm.
        evaluated = await runner.invoke(defined['pluginId'], result['pluginRunId'], 'evaluate', '40 + 2')
        assert evaluated == dict(ok=True, value=42)
        executed = await runner.invoke(defined['pluginId'], result['pluginRunId'], 'execute', 'callback_total = 42')
        assert executed == dict(ok=True, value=None)
        args = {'x': '中文', 'path': str(path)}
        reply = await runner.invoke(defined['pluginId'], result['pluginRunId'], 'read', args)
        assert reply['ok'], reply
        assert reply['value']['root'] == 9 and reply['value']['counter'] == {'a': 2, 'b': 1}
        assert reply['value']['text'] == 'Win7' and reply['value']['json'] == args
        assert reply['value']['file'] == '中文 Win7'
        assert reply['value']['date'] == '2020-01-02'
        assert reply['value']['generated'] == reply['value']['evaluated'] == 42
        assert reply['value']['callback_total'] == 42
        inspected = ctx.get('cordisInspect')
        assert inspected is not None
    finally:
        await close_web_context(ctx)
