import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from dsh.core.abort import AbortController
from dsh.llm.deepseek_wire import parse_sse
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_completions_stream import completions_events
from dsh.llm.pi_stream import to_stream_chunks
from dsh.llm.stream_bridge import OwnedStream, iter_chunks
from scripts.oracles.pi_http_python import observe_pi_http


FIXTURES = json.loads((Path(__file__).resolve().parents[1] / 'scripts/oracles/pi-fixtures.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
async def test_actual_http_tool_stream_keeps_interleaved_calls_and_replay_identity():
    fixture = next(row for row in FIXTURES if row['id'] == 'http-tool-interleaved')
    result = await observe_pi_http(fixture)
    assert result['requests'][0]['path'] == '/v1/chat/completions'
    blocks = [chunk['block'] for chunk in result['chunks'] if chunk['type'] == 'block-end']
    assert [(block['id'], json.loads(block['arguments'])) for block in blocks] == [('a', {'x': 2}), ('b', {'y': 1})]
    finish = result['chunks'][-1]
    assert finish['reason'] == {'kind': 'tool-calls'}
    assert finish['replayState']['response']['responseId'] == 'response-1'


def test_deepseek_requires_done_while_pi_completions_owns_its_finish_validation():
    data = [b'data: {"choices":[{"finish_reason":"stop"}]}\n\n']
    with pytest.raises(LlmError) as error:
        list(parse_sse(data))
    assert error.value.code == 'STREAM_CLOSED'
    assert len(list(parse_sse(data, require_done=False))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['cancel', 'idle-timeout', 'header-timeout'])
async def test_stalled_http_stream_is_cancelled_or_times_out_and_reader_closes(mode):
    opened, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            if mode == 'header-timeout':
                opened.set()
                release.wait(5)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.flush()
            opened.set()
            release.wait(5)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    controller = AbortController()
    fixture = next(row for row in FIXTURES if row['id'] == 'http-text')
    model = dict(fixture['model'], baseUrl='http://127.0.0.1:{}/v1'.format(server.server_port))
    options = dict(apiKey='oracle', streamIdleTimeoutMs=60 if mode == 'idle-timeout' else 5000)
    if mode == 'header-timeout':
        options['timeoutMs'] = 60
    source = iter_chunks(OwnedStream(lambda signal: completions_events(model, fixture['context'], options, signal), controller.signal))

    async def collect():
        return [chunk async for chunk in to_stream_chunks(source, model['contextWindow'], controller.signal)]

    task = asyncio.create_task(collect())
    try:
        assert await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(None, opened.wait, 2), 3)
        if mode == 'cancel':
            controller.abort()
        chunks = await asyncio.wait_for(task, 2)
        assert chunks[-1]['reason']['failure']['code'] == ('ABORTED' if mode == 'cancel' else 'TIMEOUT')
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await source.aclose()
        release.set()
        server.shutdown()
        server.server_close()
        worker.join()
