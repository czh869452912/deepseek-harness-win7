import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dsh.llm.pi_completions_stream import completions_events
from dsh.llm.pi_responses_stream import responses_events
from dsh.llm.pi_anthropic_stream import anthropic_events
from dsh.llm.pi_stream import to_stream_chunks
from dsh.llm.stream_bridge import OwnedStream, iter_chunks


async def observe_pi_http(fixture):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(dict(path=self.path, authorization=self.headers.get('Authorization') or self.headers.get('x-api-key'), body=body))
            if fixture['kind'] == 'anthropic-http':
                requests[-1].update(anthropicVersion=self.headers.get('anthropic-version'), beta=self.headers.get('anthropic-beta'))
            self.send_response(fixture.get('status', 200))
            self.send_header('Content-Type', 'application/json' if fixture.get('status') else 'text/event-stream')
            self.end_headers()
            if fixture.get('status'):
                self.wfile.write(json.dumps(fixture.get('errorBody', dict(error=dict(message='fixture error')))).encode('utf-8'))
            else:
                for frame in fixture['frames']:
                    if fixture['kind'] == 'anthropic-http':
                        self.wfile.write(('event: ' + frame['type'] + '\n').encode('utf-8'))
                    self.wfile.write(('data: ' + json.dumps(frame) + '\n\n').encode('utf-8'))
                if not fixture.get('omitDone'):
                    self.wfile.write(b'data: [DONE]\n\n')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    try:
        model = dict(fixture['model'], baseUrl='http://127.0.0.1:{}/v1'.format(server.server_port))
        options = dict(fixture.get('options', {}), apiKey='oracle')
        source = anthropic_events if fixture['kind'] == 'anthropic-http' else responses_events if fixture['kind'] == 'responses-http' else completions_events
        owned = OwnedStream(lambda signal: source(model, fixture['context'], options, signal))
        events = iter_chunks(owned)
        chunks = []
        try:
            async for chunk in to_stream_chunks(events, model['contextWindow']):
                if chunk['type'] == 'finish' and 'failure' in chunk['reason']:
                    chunk['reason']['failure'].pop('message', None)
                chunks.append(chunk)
        finally:
            await events.aclose()
        return dict(requests=requests, chunks=chunks)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
