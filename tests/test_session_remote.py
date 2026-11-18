import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
import yaml
from scripts.model_http_fixture import model_sse
from dsh.boot.profile_boot import run_profile
from dsh.typert.dispatch import RemoteDispatcher
from dsh.core.abort import AbortController
from dsh.session.query_current import CurrentSqliteSessionQueryEngine as SqliteSessionQueryEngine


@pytest.fixture
def local_llm(monkeypatch):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(payload)
            delta, finish = {'content': 'Verified browser reply'}, 'stop'
            texts = [m['content'] if isinstance(m.get('content'),str) else block.get('text','')
                     for m in payload['messages'] if m.get('role')=='user'
                     for block in ([{}] if isinstance(m.get('content'),str) else m.get('content',[]))]
            tool_prompt = next((text for text in texts if text.startswith('TOOL_ACCEPTANCE:')),None)
            has_result = any(m.get('role')=='tool' or any(block.get('type')=='tool_result'
                for block in m.get('content',[]) if isinstance(block,dict)) for m in payload['messages'])
            if tool_prompt and not has_result:
                delta = {'tool_calls': [{'index': 0, 'id': 'acceptance-read', 'type': 'function', 'function': {'name': 'read', 'arguments': json.dumps({'file_path': tool_prompt.split(':', 1)[1]})}}]}
                finish = 'tool_calls'
            body = model_sse(self.path,delta,finish)
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
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'local-test-only')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'http://127.0.0.1:%s' % server.server_port)
    yield requests
    server.shutdown()
    server.server_close()
    worker.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.parametrize('preset', ['minimal', 'standard', 'cordis'])
async def test_session_remote_create_follow_rename_resume(tmp_path, monkeypatch, preset, local_llm):
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED', '1')
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'home'))
    # Content search is explicitly opt-in, matching the official Web profile.
    patch = tmp_path / 'isolated.yml'
    patch.write_text(yaml.safe_dump(
        [dict(id='session-query-sqlite', config=dict(path=':memory:', openAt='first-search'))]), encoding='utf-8')
    result = await run_profile(dict(profile='web', dshHome=str(tmp_path / 'home'), patchFiles=[str(patch)],
                                   args=['--no-open', '--port', '0'], waitForExit=False))
    (tmp_path / 'AGENTS.md').write_text('WORKSPACE_RULE_38: respect Python 3.8.', encoding='utf-8')
    ctx = result['ctx']
    try:
        assert isinstance(ctx.get('sessionQuery'), SqliteSessionQueryEngine)
        remote = RemoteDispatcher(ctx)
        async def call(method, **args):
            return await remote.invoke(dict(namespace='session', method=method, args=args))
        catalog = await call('modelCatalog')
        assert 'groups' in catalog
        created = await call('create', request=dict(cwd=str(tmp_path), sessionId='session-web-test', agentPreset=preset))
        assert created['sessionId'] == 'session-web-test'
        renamed = await call('rename', request=dict(sessionId=created['sessionId'], title='Browser test'))
        assert renamed['title'] == 'Browser test'
        signal = AbortController()
        stream = ctx.get('sessionController').follow(dict(address=dict(kind='session', sessionId=created['sessionId'])), signal.signal)
        snapshot = await stream.__anext__()
        assert snapshot['type'] == 'snapshot'
        assert snapshot['header']['id'] == created['sessionId']
        assert snapshot['projections']['values']['title'] == 'Browser test'
        assert await call('prompt', request=dict(sessionId=created['sessionId'], requestId='browser-prompt', mode='queue', content=[dict(type='text', text='Please respond')])) == {'accepted': True}
        async def receive_reply():
            while True:
                frame = await stream.__anext__()
                if frame['type'] == 'event' and frame['event']['type'] == 'turn/end':
                    return frame
        await asyncio.wait_for(receive_reply(), 15)
        agent = ctx.get('agents').get(created['sessionId'])
        assert any(event['type'] == 'assistant/message' and 'Verified browser reply' in json.dumps(event) for event in agent.session.events)
        assert local_llm
        if preset == 'minimal':
            system=local_llm[-1].get('system',local_llm[-1]['messages'][0]['content'])
            assert 'You are a helpful software engineer assistant.' in (system if isinstance(system,str) else json.dumps(system))
        if preset != 'minimal':
            assert 'WORKSPACE_RULE_38' in json.dumps(local_llm[-1]['messages'])
        else:
            assert 'WORKSPACE_RULE_38' not in json.dumps(local_llm[-1]['messages'])
        search = await call('search', request={'query': 'Verified browser reply'})
        assert search['items'][0]['sessionId'] == created['sessionId']
        forked = await call('fork', request={'sessionId': created['sessionId']})
        assert forked['sessionId'] != created['sessionId']
        references = await remote.invoke(dict(namespace='sessionReferenceResolver', method='candidates',
            args=dict(agentId=forked['sessionId'], query='Browser')))
        assert references[0]['sessionId'] == created['sessionId']
        prepared = await ctx.get('sessionReferenceResolver').prepare(
            ctx.get('agents').get(forked['sessionId']), [], [dict(sessionId=created['sessionId'])])
        assert 'Verified browser reply' in prepared['additionalContext']['content'][0]['text']
        from dsh.core.abort import NEVER_ABORTED
        import io
        import zipfile
        fetch = ctx.get('connection').create_shared_fetch_handler('/api').fetch
        exported = await fetch(dict(path='/api/session.export', url='http://localhost/api/session.export?sessionId=' + created['sessionId'], method='GET', signal=NEVER_ABORTED), ctx.get('connection').browserPeer)
        assert exported['status'] == 200
        archive = b''.join([chunk async for chunk in exported['body']])
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            from dsh.session.log_export_current import read_session_log_text, SESSION_LOG_FILENAME
            logical = await read_session_log_text(ctx.get('sessionPersistence'), created['sessionId'])
            assert zipped.namelist() == [SESSION_LOG_FILENAME]
            assert zipped.read(SESSION_LOG_FILENAME) == logical.encode('utf-8')
            assert json.loads(logical.splitlines()[0])['version'] == 4
        await stream.aclose()
        listing = await call('list', _request={})
        assert created['sessionId'] in [row['sessionId'] for row in listing['items']]
    finally:
        result['shutdown'].shutdown(0)
        await result['shutdown'].wait()


    restarted = await run_profile(dict(profile='web', dshHome=str(tmp_path / 'home'), patchFiles=[str(patch)], args=['--no-open', '--port', '0'], waitForExit=False))
    try:
        ctx = restarted['ctx']
        assert isinstance(ctx.get('sessionQuery'), SqliteSessionQueryEngine)
        remote = RemoteDispatcher(ctx)
        listing = await remote.invoke(dict(namespace='session', method='list', args=dict(_request={})))
        assert created['sessionId'] in [row['sessionId'] for row in listing['items']]
        await ctx.get('sessionController').agents.resolveAgent(created['sessionId'])
        restored = ctx.get('agents').get(created['sessionId'])
        assert any(e['type'] == 'assistant/message' and 'Verified browser reply' in json.dumps(e) for e in restored.session.events)
        searched = await remote.invoke(dict(namespace='session', method='search', args=dict(request=dict(query='Verified browser reply'))))
        assert [item['sessionId'] for item in searched['items']] == [forked['sessionId'], created['sessionId']]
    finally:
        restarted['shutdown'].shutdown(0)
        await restarted['shutdown'].wait()


@pytest.mark.asyncio
async def test_web_prompt_executes_real_read_tool(tmp_path, monkeypatch, local_llm):
    from canonical_web_fixture import web_context, close_web_context
    content = tmp_path / 'input.txt'
    content.write_text('TOOL_READ_RESULT_38', encoding='utf-8')
    ctx = await web_context(tmp_path / 'home')
    try:
        controller = ctx.get('sessionController')
        await controller.create(dict(sessionId='tool-session', cwd=str(tmp_path), agentPreset='standard'))
        stream = controller.follow(dict(address=dict(kind='session', sessionId='tool-session')), AbortController().signal)
        await stream.__anext__()
        await controller.prompt(dict(sessionId='tool-session', requestId='read-request', mode='queue', content=[dict(type='text', text='TOOL_ACCEPTANCE:' + str(content))]), AbortController().signal)
        async def finish():
            async for frame in stream:
                if frame['type'] == 'event' and frame['event']['type'] == 'turn/end':
                    return frame
        end = await asyncio.wait_for(finish(), 15)
        await stream.aclose()
        def tool_results(request):
            return [m for m in request['messages'] if m.get('role') == 'tool'] + [
                block for m in request['messages'] if isinstance(m.get('content'),list)
                for block in m['content'] if block.get('type') == 'tool_result']
        assert len([r for r in local_llm if tool_results(r)]) == 1, end
        assert 'TOOL_READ_RESULT_38' in json.dumps(tool_results(local_llm[-1]))
    finally:
        await close_web_context(ctx)
