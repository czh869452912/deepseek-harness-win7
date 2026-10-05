import argparse
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PLUGIN_SOURCE = '''from pathlib import Path
from dsh.plugin_api import Plugin

class PermissionFixture(Plugin):
    inject = ["tools"]
    def apply(self, ctx, config):
        async def execute(arguments, execution):
            path = Path(execution.agent.session.header.cwd) / "permission-executed.txt"
            path.write_text("executed once", encoding="utf-8")
            return "permission tool result"
        dispose = ctx.get("tools").register({
            "name": "guarded_echo", "description": "Controlled approval fixture",
            "parameters": {"type": "object", "properties": {}}, "execute": execute,
            "output": {"schema": {"type": "string"},
                "render": lambda arguments, value: [{"type": "text", "text": value}]}})
        ctx.effect(lambda: dispose)
        ctx.on("tools/pre-execute", lambda execution, next_fn:
            {"kind": "ask"} if execution.name == "guarded_echo" else next_fn())
'''


def prepare_profile(root, workspace):
    sys.path.insert(0, str(root))
    from dsh.boot.profile import init_profile
    from dsh.boot.python_plugins import install
    home = workspace / 'home'
    profile = home / 'profiles/acp'
    init_profile(str(profile), [], 'startup')
    rows = [{'id': name, 'name': '@deepseek-ai/dsh-' + name} for name in
            ('session', 'tools', 'system-prompt', 'llm', 'llm-deepseek', 'credentials-local',
             'agent', 'agent-loop', 'user-approval', 'acp-app')]
    rows.extend([{'id': 'acp', 'name': '@deepseek-ai/dsh-acp', 'inject': ['acpAppStartup'],
        'config': {'provider': 'deepseek-official', 'model': 'deepseek-v4-flash'}},
        {'id': 'persistence', 'name': '@deepseek-ai/dsh-session-persistence-jsonl',
         'config': {'root': str(workspace / 'sessions'), 'packChunks': False}}])
    import yaml
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert': rows}]), encoding='utf-8')
    package = workspace / 'fixture'
    (package / 'python').mkdir(parents=True)
    manifest = {'name': '@verification/permission-fixture', 'version': '0.1.0',
        'dsh': {'bundle': {'patch': 'cordis.patch.yml'}, 'python': {'apiVersion': 1,
            'sourceRoot': 'python', 'entry': 'plugin:PermissionFixture',
            'minPythonVersion': [3, 8, 10], 'minHostVersion': [0, 1, 0], 'dependencies': []}}}
    (package / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    (package / 'cordis.patch.yml').write_text('- insert:\n    - id: permission-fixture\n      name: "@verification/permission-fixture"\n', encoding='utf-8')
    (package / 'python/plugin.py').write_text(PLUGIN_SOURCE, encoding='utf-8')
    install(str(profile), str(package), str(root))
    return home


class Peer:
    def __init__(self, root, workspace, home, endpoint):
        environment = {name: value for name, value in os.environ.items()
            if not re.search(r'(?:^|_)(?:API_KEY|API_TOKEN|ACCESS_TOKEN|REFRESH_TOKEN|OAUTH_TOKEN)$', name, re.I)
            and name.upper() not in ('DSH_HOME', 'PYTHONPATH', 'PYTHONHOME')}
        environment.update(DSH_HOME=str(home), DSH_TELEMETRY_DISABLED='1',
            DEEPSEEK_API_KEY='fixture-only', DEEPSEEK_BASE_URL=endpoint)
        command = [sys.executable] + (['-I'] if (root / 'python.exe').is_file() else [])
        self.process = subprocess.Popen(command + ['-u', str(root / 'dsh.py'), '--profile', 'acp'],
            cwd=str(workspace), env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, encoding='utf-8', bufsize=1)
        self.frames, self.observed, self.errors = queue.Queue(), [], []
        def read():
            for line in self.process.stdout:
                self.frames.put(json.loads(line))
            self.frames.put({'eof': True})
        self.reader = threading.Thread(target=read, daemon=True)
        self.stderr = threading.Thread(target=lambda: self.errors.append(self.process.stderr.read()), daemon=True)
        self.reader.start()
        self.stderr.start()

    def send(self, packet):
        self.process.stdin.write(json.dumps(packet) + '\n')
        self.process.stdin.flush()

    def request(self, identity, method, params):
        self.send({'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params})

    def wait(self, predicate):
        while True:
            try:
                packet = self.frames.get(timeout=15)
            except queue.Empty:
                raise RuntimeError('ACP permission timed out: ' + repr(self.errors))
            if packet.get('eof'):
                raise RuntimeError('Unexpected permission EOF: ' + repr(self.errors))
            self.observed.append(packet)
            if predicate(packet):
                return packet

    def reply(self, identity):
        return self.wait(lambda packet: packet.get('id') == identity)

    def finish(self):
        self.process.stdin.close()
        if self.process.wait(timeout=10) != 0:
            raise RuntimeError('ACP permission process failed')
        self.reader.join(2)
        self.stderr.join(2)
        if self.errors != [''] or self.frames.get(timeout=1) != {'eof': True}:
            raise RuntimeError('ACP permission late output/diagnostics: ' + repr(self.errors))

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=3)
        self.reader.join(2)
        self.stderr.join(2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


def journey(root, workspace, modes=None):
    home = prepare_profile(root, workspace)
    from dsh.session.jsonl_zstd import decompress_frame, scan_frames
    selected = modes or ['allow', 'reject', 'malformed', 'cancel-late', 'close-late', 'eof']
    rows, requests = [], []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            second = any(message.get('role') == 'tool' for message in request['messages'])
            delta = {'content': 'finished after decision'} if second else {'tool_calls': [
                {'index': 0, 'id': 'call-9', 'type': 'function',
                 'function': {'name': 'guarded_echo', 'arguments': '{}'}}]}
            chunk = {'choices': [{'delta': delta, 'finish_reason': 'stop' if second else 'tool_calls'}]}
            body = ('data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for mode in selected:
            directory = workspace / mode
            directory.mkdir()
            first = len(requests)
            peer = Peer(root, directory, home, 'http://127.0.0.1:' + str(server.server_port))
            try:
                peer.request(1, 'initialize', {'protocolVersion': 1})
                assert peer.reply(1)['result']['protocolVersion'] == 1
                peer.request(2, 'session/new', {'cwd': str(directory), 'mcpServers': []})
                created = peer.reply(2)
                assert 'result' in created, created
                session_id = created['result']['sessionId']
                peer.request(3, 'session/prompt', {'sessionId': session_id,
                    'prompt': [{'type': 'text', 'text': 'request the controlled tool'}]})
                permission = peer.wait(lambda packet: packet.get('method') == 'session/request_permission')
                assert permission['params'] == {'sessionId': session_id, 'toolCall': {'toolCallId': 'call-9'}, 'options': [
                    {'optionId': 'allow-once', 'name': 'Allow once', 'kind': 'allow_once'},
                    {'optionId': 'reject-once', 'name': 'Reject', 'kind': 'reject_once'}]}
                assert any(packet.get('method') == 'session/update' and
                    packet['params']['update'].get('sessionUpdate') == 'tool_call' for packet in peer.observed[:-1])
                marker = directory / 'permission-executed.txt'
                assert not marker.exists() and len(requests) == first + 1
                if mode == 'eof':
                    peer.finish()
                elif mode in ('cancel-late', 'close-late'):
                    if mode == 'cancel-late':
                        peer.send({'jsonrpc': '2.0', 'method': 'session/cancel', 'params': {'sessionId': session_id}})
                        assert peer.reply(3)['result'] == {'stopReason': 'cancelled'}
                    else:
                        peer.request(4, 'session/close', {'sessionId': session_id})
                        found = {}
                        while set(found) != {3, 4}:
                            packet = peer.wait(lambda packet: packet.get('id') in (3, 4))
                            assert packet['id'] not in found, packet
                            found[packet['id']] = packet
                        assert found[3]['result'] == {'stopReason': 'cancelled'} and found[4]['result'] == {}
                    peer.send({'jsonrpc': '2.0', 'id': permission['id'],
                        'result': {'outcome': {'outcome': 'selected', 'optionId': 'allow-once'}}})
                    peer.request(5, 'session/list', {})
                    assert 'sessions' in peer.reply(5)['result']
                    peer.finish()
                else:
                    outcome = {'outcome': 'unknown', 'optionId': 'allow-once'} if mode == 'malformed' else {
                        'outcome': 'selected', 'optionId': 'allow-once' if mode == 'allow' else 'reject-once'}
                    peer.send({'jsonrpc': '2.0', 'id': permission['id'], 'result': {'outcome': outcome}})
                    assert peer.reply(3)['result'] == {'stopReason': 'end_turn'}
                    assert len(requests) == first + 2
                    assert any(message.get('role') == 'tool' for message in requests[-1]['messages'])
                    assert ('permission tool result' in str(requests[-1]['messages'])) is (mode == 'allow'), requests[-1]['messages']
                    peer.finish()
                assert marker.exists() is (mode == 'allow')
                if mode in ('cancel-late', 'close-late', 'eof'):
                    assert len(requests) == first + 1
                files = [path for path in (workspace / 'sessions').rglob('session.jsonl.zstd') if path.parent.name == session_id]
                assert len(files) == 1, files
                buffer = files[0].read_bytes()
                scanned = scan_frames(buffer)
                assert 'tornStart' not in scanned and scanned['frames'], scanned
                text = b''.join(decompress_frame(buffer[frame['start']:frame['end']])
                                for frame in scanned['frames']).decode('utf-8')
                events = [json.loads(line) for line in text.splitlines()[1:]]
                audit = [event for event in events if event['type'] in ('approval/asked', 'approval/decided')]
                expected = {'allow': 'allowed-once', 'reject': 'rejected', 'malformed': 'unavailable'}.get(mode, 'cancelled')
                assert [event['type'] for event in audit] == ['approval/asked', 'approval/decided']
                assert audit[0]['data']['id'] == audit[1]['data']['id'] and audit[1]['data']['outcome'] == expected
                rows.append({'mode': mode, 'executed': marker.exists(), 'modelRequests': len(requests) - first,
                    'permission': permission, 'frames': peer.observed, 'stderr': peer.errors, 'audit': audit})
            finally:
                peer.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
    return {'modes': selected, 'processes': len(selected), 'observations': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({'result': 'passed', 'value': journey(args.root.resolve(), args.workspace.resolve())}, ensure_ascii=True))
