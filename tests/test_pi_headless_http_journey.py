"""Real default headless consumer of each native pi-ai wire protocol."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml


@pytest.mark.parametrize('protocol', ['openai-completions', 'openai-responses', 'anthropic-messages'])
def test_headless_pi_provider_tool_result_replay_and_persistence(tmp_path, protocol):
    calls = []
    target = tmp_path / 'evidence.txt'
    target.write_text('PI-NATIVE-TOOL-EVIDENCE', encoding='utf-8')
    arguments = dict(command='view', path=str(target))
    final = 'Native protocol journey complete.'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            main = body.get('tools') and body.get('model') == 'fixture-model'
            if main:
                calls.append(body)
            use_tool = main and len(calls) == 1
            frames = []
            if not main or protocol == 'openai-completions':
                delta = dict(tool_calls=[dict(index=0, id='call-read', type='function', function=dict(name='str_replace_editor', arguments=json.dumps(arguments)))]) if use_tool else dict(content=final if main else 'Inspect file')
                frames = [dict(choices=[dict(delta=delta, finish_reason='tool_calls' if use_tool else 'stop')])]
            elif protocol == 'openai-responses':
                item = dict(type='function_call', id='fc_read', call_id='call-read', name='str_replace_editor', arguments=json.dumps(arguments)) if use_tool else dict(type='message', id='msg_final', role='assistant', content=[dict(type='output_text', text=final)])
                frames = [dict(type='response.output_item.done', output_index=0, item=item),
                          dict(type='response.completed', response=dict(id='resp', status='completed'))]
            else:
                block = dict(type='tool_use', id='call-read', name='str_replace_editor', input={}) if use_tool else dict(type='text', text=final)
                frames = [dict(type='message_start', message=dict(id='msg', usage=dict(input_tokens=10))),
                          dict(type='content_block_start', index=0, content_block=block)]
                if use_tool:
                    frames.append(dict(type='content_block_delta', index=0, delta=dict(type='input_json_delta', partial_json=json.dumps(arguments))))
                frames.extend([dict(type='content_block_stop', index=0), dict(type='message_delta', delta=dict(stop_reason='tool_use' if use_tool else 'end_turn')), dict(type='message_stop')])
            text = ''.join(('event: ' + frame['type'] + '\n' if main and protocol == 'anthropic-messages' else '') +
                           'data: ' + json.dumps(frame) + '\n\n' for frame in frames)
            if not main or protocol == 'openai-completions':
                text += 'data: [DONE]\n\n'
            data = text.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    endpoint = 'http://127.0.0.1:{}'.format(server.server_port)
    patch = tmp_path / 'model.yaml'
    patch.write_text(yaml.safe_dump([
        dict(id='llm-pi-ai', config=dict(providers=dict(gateway=dict(api=protocol, baseURL=endpoint,
            apiKeyEnv='TEST_PI_KEY', models=[dict(id='fixture-model')])))),
        dict(id='agent-default-model', config=dict(provider='gateway', model='fixture-model')),
    ]), encoding='utf-8')
    env = dict(os.environ, DSH_HOME=str(tmp_path / 'home'), DSH_TELEMETRY_DISABLED='1', TEST_PI_KEY='fixture',
               DEEPSEEK_API_KEY='fixture', DEEPSEEK_BASE_URL=endpoint)
    try:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'dsh.py'),
            '--profile', 'headless', '--patch', str(patch), 'Read evidence.txt'], cwd=str(tmp_path), env=env,
            capture_output=True, encoding='utf-8', timeout=25)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout.strip() == final
        assert len(calls) == 2
        assert 'PI-NATIVE-TOOL-EVIDENCE' in json.dumps(calls[1])
        logs = list((tmp_path / 'home/sessions').rglob('session.jsonl'))
        assert len(logs) == 1
        events = [json.loads(line) for line in logs[0].read_text(encoding='utf-8').splitlines()]
        results = [event for event in events if event['type'] == 'tool/result']
        assert len(results) == 1 and 'PI-NATIVE-TOOL-EVIDENCE' in json.dumps(results)
        assert 'pi-ai' in json.dumps(events) and protocol in json.dumps(events)
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
