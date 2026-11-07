"""Default migrated Cordis guidance and separately mounted native delivery resources."""
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apps.cli import plugin as cli
from dsh.boot.profile_boot import run_profile
from dsh.core.abort import NEVER_ABORTED
from dsh.core.scope import scope_of
from dsh.core.tools import ToolExecutionInput
from dsh.extensions.cordis_manager import _share_builtin_provider
from dsh.extensions.inspect_registry import CordisInspectRegistryService
from dsh.cordis.context import Context
from dsh.skill.canonical_filesystem import CanonicalSkillFilesystem
from canonical_web_fixture import web_context, close_web_context
from test_python_plugin_distribution import profile, boot, close, echo

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / 'packages/preset/agent-presets/presets/cordis/skills'
SKILL_NAME = 'cordis-plugin-development'
EXAMPLES = SKILL_ROOT / SKILL_NAME / 'examples'


@pytest.mark.parametrize('renamed', [False, True], ids=['default-tool', 'custom-tool'])
def test_shipped_stateful_verifier_from_foreign_directory(tmp_path, renamed):
    work = tmp_path / '外部 工作目录'
    work.mkdir()
    source = EXAMPLES / 'stateful.host.py'
    extra = []
    if renamed:
        source = work / 'counter.py'
        source.write_text((EXAMPLES / 'stateful.host.py').read_text(encoding='utf-8').replace(
            "'win7_state_counter'", "'eval_counter'"), encoding='utf-8')
        extra = ['eval_counter']
    process = subprocess.run([sys.executable, str(EXAMPLES / 'verify_stateful.py'), str(ROOT), str(source)] + extra,
        cwd=str(work), capture_output=True, timeout=60)
    (tmp_path / 'stateful-verifier.log').write_bytes(process.stdout + process.stderr)
    assert process.returncode == 0, process.stdout.decode('utf-8', errors='replace') + process.stderr.decode('utf-8', errors='replace')
    report = json.loads(process.stdout.decode('utf-8').splitlines()[-1])
    assert report['passed'] and report['values'] == [1, 2, 1]
    assert report['eventObserved'] and report['timerObserved'] and report['stoppedStateStable']


@pytest.mark.skipif(not os.environ.get('DSH_TEST_CHROMIUM'), reason='real browser lane: set DSH_TEST_CHROMIUM')
def test_shipped_guide_installed_browser_journey(tmp_path):
    report = tmp_path / 'guide-browser.json'
    process = subprocess.run(['node', str(ROOT / 'scripts/win7_authoring_browser_oracle.mjs'),
        '--browser', os.environ['DSH_TEST_CHROMIUM'], '--output', str(report)],
        cwd=str(ROOT), capture_output=True, timeout=300)
    (tmp_path / 'browser.log').write_bytes(process.stdout + process.stderr)
    assert process.returncode == 0, process.stdout.decode('utf-8', errors='replace') + process.stderr.decode('utf-8', errors='replace')
    assert json.loads(report.read_text(encoding='utf-8'))['passed']


@pytest.mark.asyncio
async def test_builtin_inspect_lease_survives_owner_changes_without_weakening_register():
    from scripts.oracles.inspect_python import manifest
    ctx = Context()
    registry = CordisInspectRegistryService(ctx)
    descriptor = manifest()
    first = dict(manifest=descriptor, query=lambda *_: dict(value=1))
    second = dict(manifest=descriptor, query=lambda *_: dict(value=2))
    try:
        release_first = _share_builtin_provider(registry, first)
        with pytest.raises(ValueError, match='already registered'):
            registry.register(second)
        release_second = _share_builtin_provider(registry, second)
        assert len(registry.list()) == 1
        assert await registry.query('host', 'probe', 'read', {}, None, NEVER_ABORTED) == dict(value=2)
        release_first()
        release_first()
        assert await registry.query('host', 'probe', 'read', {}, None, NEVER_ABORTED) == dict(value=2)
        release_second()
        assert registry.list() == []
        release_second()
        release = _share_builtin_provider(registry, first)
        release_newest = _share_builtin_provider(registry, second)
        release_newest()
        assert await registry.query('host', 'probe', 'read', {}, None, NEVER_ABORTED) == dict(value=1)
        release()
    finally:
        await ctx.fiber.dispose()


def copy_preset(home, name):
    source = ROOT / 'packages/preset/agent-presets/presets/cordis'
    target = home / '.agent-presets' / name
    shutil.copytree(str(source), str(target))
    path = target / 'agent.cordis.yml'
    with path.open('a', encoding='utf-8') as stream:
        stream.write("\n- id: tool-python-export\n  name: '@deepseek-ai/dsh-tool-python-export'\n")
    return target


@pytest.fixture
def recording_llm(monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(payload)
            text = json.dumps(payload['messages'])
            if payload.get('tools') and SKILL_NAME in text and not any(row['role'] == 'tool' for row in payload['messages']):
                delta = {'tool_calls': [{'index': 0, 'id': 'load-win7', 'type': 'function',
                    'function': {'name': 'skill', 'arguments': json.dumps({'name': SKILL_NAME})}}]}
                finish = 'tool_calls'
            else:
                delta, finish = {'content': 'Authoring request observed'}, 'stop'
            body = ('data: ' + json.dumps({'choices': [{'delta': delta, 'finish_reason': finish}]})
                    + '\n\ndata: [DONE]\n\n').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'local-authoring-fixture')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'http://127.0.0.1:' + str(server.server_port))
    yield requests
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize('surface', ['creative', 'web'])
@pytest.mark.parametrize('enabled', [False, True], ids=['default', 'explicit-export'])
async def test_formal_first_request_and_actual_skill_load(tmp_path, monkeypatch, recording_llm, surface, enabled):
    home = tmp_path / 'home'
    monkeypatch.setenv('DSH_HOME', str(home))
    monkeypatch.setenv('DSH_AGENTS_HOME', str(tmp_path / 'empty-agents'))
    monkeypatch.setenv('DSH_TELEMETRY_MODE', 'DISABLED')
    monkeypatch.delenv('DSH_BUNDLED_SKILL_DIR', raising=False)
    monkeypatch.chdir(tmp_path)
    if surface == 'web' and enabled:
        copy_preset(home, 'cordis-win7')
    patch = tmp_path / 'export.patch.yml'
    patch.write_text("- insert:\n    - id: tool-python-export\n      name: '@deepseek-ai/dsh-tool-python-export'\n", encoding='utf-8')
    result = await run_profile(dict(profile=surface, dshHome=str(home),
        patchFiles=[str(patch)] if surface == 'creative' and enabled else [],
        args=['--no-open', '--port', '0'] if surface == 'web' else ['Develop a read-only Python plugin'],
        waitForExit=False))
    try:
        ctx = result['ctx']
        if surface == 'web':
            controller = ctx.get('sessionController')
            await controller.create(dict(sessionId='author', cwd=str(tmp_path),
                                         agentPreset='cordis-win7' if enabled else 'cordis'))
            await controller.prompt(dict(sessionId='author', requestId='author-request', mode='queue',
                                         content=[dict(type='text', text='Develop a read-only Python plugin')]), NEVER_ABORTED)
            await asyncio.wait_for(ctx.get('agents').get('author').whenIdle(), 30)
        else:
            await asyncio.wait_for(result['shutdown'].wait(), 30)
        agent_requests = [row for row in recording_llm if row.get('tools')]
        assert len(agent_requests) == 2
        first = agent_requests[0]
        names = [row['function']['name'] for row in first['tools']]
        assert ('cordis_export' in names) is enabled
        assert 'Python 3.8.10' in json.dumps(first['messages'])
        assert SKILL_NAME in json.dumps(first['messages'])
        assert 'load the cordis-plugin-development Skill' in json.dumps(first['messages'])
        assert 'restricted builtins and computation imports' in json.dumps(first['messages'])
        assert 'trusted DSH process with Python builtins and imports' not in json.dumps(first['messages'])
        assert 'cordis-plugin-development-win7' not in json.dumps(first['messages'])
        define_description = next(row['function']['description'] for row in first['tools']
                                  if row['function']['name'] == 'cordis_define')
        assert 'Python Host syntax, and JavaScript Client syntax' in define_description
        assert 'syntax failures are reported during browser activation' not in define_description
        cordis_names = [name for name in names if name.startswith('cordis_') and name != 'cordis_export']
        assert cordis_names == sorted(['cordis_inspect_list', 'cordis_inspect_query', 'cordis_inspect_self',
                                       'cordis_define', 'cordis_run', 'cordis_stop', 'cordis_undefine'])
        tool_message = next(row for row in agent_requests[1]['messages'] if row['role'] == 'tool')
        body = tool_message['content']
        assert 'ctx.tools.register' in body and 'harness.defineTool' in body
        assert 'Python 3.8.10' in body and 'plain JavaScript' in body
        assert 'restricted builtins and computation imports' in body
        assert 'Define checks Python Host and JavaScript Client syntax without executing either half.' in body
        assert 'execution errors, missing dependencies, or browser engine differences' in body
        assert 'Client parse failures are currently reported during browser activation' not in body
        assert 'references/delivery.md' not in body and 'cordis_export' not in body
        assert '## Modify @pluginId' in body and '## Versions, approval, and repair' in body
        (tmp_path / 'observed-requests.json').write_text(json.dumps(recording_llm, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        result['shutdown'].shutdown(0)
        await result['shutdown'].wait()


@pytest.mark.asyncio
async def test_default_skill_user_shadowing_and_optional_export_are_separate(tmp_path):
    home = tmp_path / 'home'
    for preset in ('dev-a', 'dev-b'):
        copy_preset(home, preset)
    before = {preset: (home / '.agent-presets' / preset / 'agent.cordis.yml').read_bytes() for preset in ('dev-a', 'dev-b')}
    ctx = await web_context(home)
    try:
        for sid in ('owner', 'foreign'):
            await ctx.get('sessionController').create(dict(sessionId=sid, cwd=str(tmp_path), agentPreset='cordis'))
        owner, foreign = [ctx.get('agents').get(sid) for sid in ('owner', 'foreign')]
        for sid, preset in [('preset-a', 'dev-a'), ('preset-shared', 'dev-a'), ('preset-b', 'dev-b')]:
            await ctx.get('sessionController').create(dict(sessionId=sid, cwd=str(tmp_path), agentPreset=preset))
            agent = ctx.get('agents').get(sid)
            loaded = await ctx.get('skills').get(SKILL_NAME, dict(cwd=str(tmp_path), scope=scope_of(agent.ctx)))
            assert loaded['provider'] == 'filesystem'
            assert 'Python 3.8.10' in loaded['content']
            assert 'cordis_export' in {row['name'] for row in ctx.get('tools').schemas(agent)}
        assert 'cordis_export' not in {row['name'] for row in ctx.get('tools').schemas(foreign)}
        for candidate in (owner, foreign, agent):
            inspected = await ctx.get('cordisInspect').query('host', 'Tool', 'listTools', {}, candidate, NEVER_ABORTED)
            assert inspected['tools'] == ctx.get('tools').schemas(candidate)
        assert all((home / '.agent-presets' / preset / 'agent.cordis.yml').read_bytes() == original for preset, original in before.items())
        options = dict(cwd=str(tmp_path), scope=scope_of(owner.ctx))
        skills = ctx.get('skills')
        original = await skills.get(SKILL_NAME, options)
        assert original['provider'] == 'filesystem'
        assert await skills.get('cordis-plugin-development-win7', options) is None
        custom = tmp_path / 'user-skills'
        custom.mkdir()
        (custom / 'shadow.md').write_text('---\nname: ' + SKILL_NAME + '\ndescription: User override\n---\nUser source', encoding='utf-8')
        shadow = await owner.ctx.plugin(CanonicalSkillFilesystem, dict(providerName='user-authoring-test',
            customSkillDirs=[str(custom)], includeDefaultRoots=False, watch=False))
        assert (await skills.get(SKILL_NAME, options))['content'] == 'User source'
        assert (await skills.get(SKILL_NAME, dict(cwd=str(tmp_path), scope=scope_of(foreign.ctx))))['content'] == original['content']
        await shadow.dispose()
        await shadow.await_settled()
        assert (await skills.get(SKILL_NAME, options))['content'] == original['content']
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_shipped_lifecycle_events_timer_and_async_cleanup(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        await ctx.get('sessionController').create(dict(sessionId='lifecycle', cwd=str(tmp_path), agentPreset='cordis'))
        owner = ctx.get('agents').get('lifecycle')
        runner = ctx.get('dynamicCordisRunner')
        source = (EXAMPLES / 'lifecycle.host.py').read_text(encoding='utf-8')
        receipt = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='life'),
            name='Owned lifecycle', purpose='Exercise guide event/timer/cleanup', code=dict(host=source)))
        started = await runner.run(owner, receipt['pluginId'], receipt['packageId'], 'run')
        assert started['ok'], started.get('stack', started)
        state = ctx.get('win7AuthoringLifecycle')
        assert state is not None
        ctx.emit('win7-authoring/notice', 2)
        await ctx.serial('win7-authoring/serial', 3)
        await ctx.parallel('win7-authoring/parallel', 4)
        data = {}
        await ctx.waterfall('win7-authoring/middleware', data)
        assert data == {'visited': True}
        for _ in range(50):
            if state['timer']:
                break
            await asyncio.sleep(0.01)
        assert state['timer'] > 0
        assert [state[key] for key in ('notice', 'serial', 'parallel')] == [2, 3, 4]
        assert (await runner.stop(owner, receipt['pluginId']))['ok']
        assert state['cancelled']
        assert ctx.get('win7AuthoringLifecycle') is None
        snapshot = dict(state)
        ctx.emit('win7-authoring/notice', 9)
        await ctx.serial('win7-authoring/serial', 9)
        await ctx.parallel('win7-authoring/parallel', 9)
        await asyncio.sleep(0.05)
        assert state == snapshot
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_shipped_dynamic_examples_and_legacy_snippet_execute_and_unwind(tmp_path):
    ctx = await web_context(tmp_path / 'home')
    try:
        await ctx.get('sessionController').create(dict(sessionId='samples', cwd=str(tmp_path), agentPreset='cordis'))
        owner = ctx.get('agents').get('samples')
        runner, tools = ctx.get('dynamicCordisRunner'), ctx.get('tools')
        legacy = (EXAMPLES.parent / 'SKILL.md').read_text(encoding='utf-8')
        snippet = re.search(r'Python Host example:\n\n```python\n(.*?)\n```', legacy, re.S).group(1)
        import textwrap
        sources = [(EXAMPLES / 'echo.host.py').read_text(encoding='utf-8'), textwrap.dedent(snippet),
                   (EXAMPLES / 'counter.host.py').read_text(encoding='utf-8')]
        for source in sources:
            receipt = runner.define(dict(sessionId=owner.id, plugin=dict(kind='new', idPrefix='guide'),
                name='Guide example', purpose='Execute shipped source', code=dict(host=source)))
            started = await runner.run(owner, receipt['pluginId'], receipt['packageId'], 'run')
            assert started['ok'], started
            name = 'win7_counted_echo' if 'win7_counted_echo' in source else 'win7_echo'
            result = await tools.execute(ToolExecutionInput('guide-call', name, dict(text='中文 Win7'), agent=owner, signal=NEVER_ABORTED))
            assert not result.is_error, result.error
            assert result.value == (dict(text='中文 Win7', calls=1) if name == 'win7_counted_echo' else '中文 Win7')
            invalid = await tools.execute(ToolExecutionInput('bad-guide-call', name, dict(text=3), agent=owner, signal=NEVER_ABORTED))
            assert invalid.is_error
            assert (await runner.stop(owner, receipt['pluginId']))['ok']
            assert tools.get(name, scope_of(owner.ctx)) is None
            stale = await runner.invoke(receipt['pluginId'], started['pluginRunId'], 'snapshot', {})
            assert not stale['ok']
    finally:
        await close_web_context(ctx)


@pytest.mark.asyncio
async def test_portable_skill_native_scaffold_is_self_contained(profile, tmp_path):
    content = (ROOT / 'docs/plugin-distribution-win7.md').read_text(encoding='utf-8')
    descriptor = json.loads(re.search(r'```json\n(.*?)\n```', content, re.S).group(1))
    code = re.search(r'```python\n(.*?)\n```', content, re.S).group(1)
    patch = re.search(r'```yaml\n(.*?)\n```', content, re.S).group(1)
    project = tmp_path / '中文 Win7 项目'
    package = project / 'python/my_plugin'
    package.mkdir(parents=True)
    (project / 'package.json').write_text(json.dumps(descriptor), encoding='utf-8')
    (project / 'cordis.patch.yml').write_text(patch, encoding='utf-8')
    (project / 'README.md').write_text('Standalone skill example', encoding='utf-8')
    (project / 'LICENSE').write_text((ROOT / 'examples/python-echo/LICENSE').read_text(encoding='utf-8'), encoding='utf-8')
    (package / '__init__.py').write_text('', encoding='utf-8')
    (package / 'plugin.py').write_text(code, encoding='utf-8')
    archive = tmp_path / 'standalone.zip'
    assert cli.run_plugin('python-test', ['pack', str(project), str(archive)]) == 0
    assert cli.run_plugin('python-test', ['add', str(archive)]) == 0
    result = await boot(profile[0])
    try:
        answer = await result['ctx'].get('tools').execute(ToolExecutionInput('native-doc', 'my_echo', dict(text='中文 Win7'), signal=NEVER_ABORTED))
        assert not answer.is_error, answer.error
        assert answer.value == '中文 Win7'
    finally:
        await close(result)
    assert cli.run_plugin('python-test', ['remove', '@author/my-plugin']) == 0


@pytest.mark.asyncio
async def test_shipped_native_package_pack_cold_start_upgrade_rollback(profile, tmp_path):
    source = tmp_path / 'native'
    shutil.copytree(str(ROOT / 'examples/python-echo'), str(source))
    first = tmp_path / 'echo-1.zip'
    assert cli.run_plugin('python-test', ['pack', str(source), str(first)]) == 0
    assert cli.run_plugin('python-test', ['add', str(first)]) == 0
    home, _ = profile
    for _ in range(2):
        result = await boot(home)
        try:
            assert await echo(result['ctx'], '中文') == 'Python echo: 中文'
        finally:
            await close(result)
    manifest_path = source / 'package.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['version'] = '0.2.0'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    formatting = source / 'python/echo/formatting.py'
    formatting.write_text(formatting.read_text(encoding='utf-8').replace('Python echo:', 'Python v2:'), encoding='utf-8')
    second = tmp_path / 'echo-2.zip'
    assert cli.run_plugin('python-test', ['pack', str(source), str(second)]) == 0
    assert cli.run_plugin('python-test', ['upgrade', str(second)]) == 0
    result = await boot(home)
    try:
        assert await echo(result['ctx'], '中文') == 'Python v2: 中文'
    finally:
        await close(result)
    assert cli.run_plugin('python-test', ['rollback', '@example/python-echo', '0.1.0']) == 0
    result = await boot(home)
    try:
        assert await echo(result['ctx'], '中文') == 'Python echo: 中文'
    finally:
        await close(result)
    assert cli.run_plugin('python-test', ['remove', '@example/python-echo']) == 0
