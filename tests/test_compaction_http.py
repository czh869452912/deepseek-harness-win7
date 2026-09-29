import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dsh.compaction.engine import CompactionEngine
from dsh.cordis.context import Context
from dsh.cordis.environment import LaunchEnvironmentSnapshot
from dsh.core.agent import Agent, AgentOptions
from dsh.core.session import Session
from dsh.llm.llm_deepseek import DeepSeekAdapter
from dsh.llm.llm_service import LLMService
from dsh.llm.token_meter import TokenMeter


@pytest.mark.asyncio
async def test_real_auxiliary_http_summary_reuses_prefix_and_flushes_checkpoint(tmp_path):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            payload = {'choices': [{'delta': {'content': 'Preserve the requested implementation and its tests.'}, 'finish_reason': 'stop'}]}
            raw = ('data: ' + json.dumps(payload) + '\n\ndata: [DONE]\n\n').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([{'source': 'process', 'values': {'DEEPSEEK_API_KEY': 'loopback-only'}}]))
    llm = LLMService(ctx)
    ctx.set_service('llm', llm)
    adapter = DeepSeekAdapter(ctx, {'baseURL': 'http://127.0.0.1:%s' % server.server_port})
    llm.register_adapter(['deepseek-official'], adapter)
    ctx.set_service('token_meter', TokenMeter(ctx))
    session = Session(session_id='http-compaction', ctx=ctx)
    session.append_request_header({'config': {'provider': 'deepseek-official', 'model': 'routed-model'},
                                   'system': 'Original system prefix', 'tools': []})
    original = 'Detailed implementation context. ' * 300
    session.append_user_message(original)
    session.append_user_message('Keep this recent question verbatim')
    agent = Agent(session, AgentOptions(provider='wrong-fallback', model='wrong'), ctx=ctx)
    durable = tmp_path / 'session.jsonl'
    def persist(current):
        durable.write_text('\n'.join(json.dumps(event, ensure_ascii=False) for event in current.events), encoding='utf-8')
    ctx.on('session/flush', persist)
    try:
        result = await CompactionEngine(ctx=ctx).compact_now(agent)
        assert len(requests) == 1
        request = requests[0]
        assert request['model'] == 'routed-model'
        assert request['messages'][0] == {'role': 'system', 'content': 'Original system prefix'}
        assert request['messages'][1]['content'] == original
        assert 'compaction engine' in request['messages'][-1]['content']
        events = [json.loads(line) for line in durable.read_text(encoding='utf-8').splitlines()]
        assert events[-1]['type'] == 'compaction/end'
        assert events[result['summarySeq']]['data']['llmStreamCall'] is True
        assert result['shadowedSeqs'] == [1]
        assert 'Preserve the requested implementation' in str(session.derive_messages()[0])
        assert session.derive_messages()[-1]['content'][0]['text'] == 'Keep this recent question verbatim'
    finally:
        await adapter.close()
        await ctx.fiber.dispose()
        server.shutdown()
        server.server_close()
        worker.join(2)
