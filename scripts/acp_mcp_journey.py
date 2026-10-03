import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from acp_permission_journey import Peer


def process_exited(identity):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, identity)
        if not handle:
            if ctypes.get_last_error() == 87:
                return True
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(identity, 0)
        return False
    except ProcessLookupError:
        return True


STDIO_PEER = '''import json,os,sys
from pathlib import Path
record=Path(sys.argv[1])
def event(kind):
 with record.open("a",encoding="utf-8") as stream:
  stream.write(json.dumps({"kind":kind,"pid":os.getpid(),"cwd":os.getcwd(),"token":os.environ.get("SESSION_TOKEN")})+"\\n")
event("started")
for line in sys.stdin:
 packet=json.loads(line)
 if "id" not in packet:
  continue
 reply={"jsonrpc":"2.0","id":packet["id"]}
 if packet["method"]=="initialize":
  reply["result"]={"protocolVersion":"2025-11-25","capabilities":{"tools":{}},"serverInfo":{"name":"controlled","version":"1"}}
 elif packet["method"]=="tools/list":
  reply["result"]={"tools":[{"name":"echo","inputSchema":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}]}
 else:
  event("called")
  reply["result"]={"content":[{"type":"text","text":packet["params"]["arguments"]["text"]}]}
 print(json.dumps(reply),flush=True)
event("closed")
'''


def prepare_profile(root, workspace):
    sys.path.insert(0, str(root))
    from dsh.boot.profile import init_profile
    import yaml
    home = workspace / 'home'
    profile = home / 'profiles/acp'
    init_profile(str(profile), [], 'startup')
    rows = [{'id': name, 'name': '@deepseek-ai/dsh-' + name} for name in
            ('session', 'tools', 'system-prompt', 'llm', 'llm-deepseek', 'credentials-local',
             'agent', 'agent-loop', 'acp-app')]
    rows.extend([{'id': 'acp', 'name': '@deepseek-ai/dsh-acp', 'inject': ['acpAppStartup'],
        'config': {'provider': 'deepseek-official', 'model': 'deepseek-v4-flash'}},
        {'id': 'persistence', 'name': '@deepseek-ai/dsh-session-persistence-jsonl',
         'config': {'root': str(workspace / 'sessions'), 'packChunks': False}}])
    (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert': rows}]), encoding='utf-8')
    return home


def journey(root, workspace):
    home = prepare_profile(root, workspace)
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            last_user = max(index for index, message in enumerate(request['messages']) if message['role'] == 'user')
            second = any(message['role'] == 'tool' for message in request['messages'][last_user + 1:])
            delta = {'content': 'MCP consumer finished'} if second else {'tool_calls': [
                {'index': 0, 'id': 'owned-echo', 'type': 'function', 'function': {
                    'name': 'mcp__fixture__echo', 'arguments': '{"text":"actual ACP MCP consumer"}'}}]}
            body = ('data: ' + json.dumps({'choices': [{'delta': delta,
                'finish_reason': 'stop' if second else 'tool_calls'}]}) + '\n\ndata: [DONE]\n\n').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = 'http://127.0.0.1:%s' % server.server_port
    peer_file, records = workspace / 'stdio-peer.py', workspace / 'stdio-records.jsonl'
    peer_file.write_text(STDIO_PEER, encoding='utf-8')
    declarations = [{'name': 'fixture', 'command': sys.executable, 'args': [str(peer_file), str(records)],
                     'env': [{'name': 'SESSION_TOKEN', 'value': 'session-owned'}]}]
    peer, http = None, None
    try:
        peer = Peer(root, workspace, home, endpoint)
        def call(identity, method, params):
            peer.request(identity, method, params)
            frame = peer.reply(identity)
            if 'error' in frame:
                raise RuntimeError('ACP MCP call failed: ' + json.dumps(frame))
            return frame['result']
        initialized = call(1, 'initialize', {'protocolVersion': 1})
        if initialized['agentCapabilities'].get('mcpCapabilities') != {'http': True}:
            raise RuntimeError('ACP MCP HTTP capability is absent')
        params = {'cwd': str(workspace), 'mcpServers': declarations}
        first = call(2, 'session/new', params)
        second = call(3, 'session/new', params)
        def prompt(identity, created, text):
            result = call(identity, 'session/prompt', dict(created, prompt=[{'type': 'text', 'text': text}]))
            if result != {'stopReason': 'end_turn'}:
                raise RuntimeError('ACP MCP prompt did not finish: ' + repr(result))
        prompt(4, first, 'first stdio')
        call(5, 'session/close', first)
        prompt(6, second, 'sibling stdio')
        call(7, 'session/resume', dict(first, **params))
        prompt(8, first, 'fresh stdio resume')
        call(9, 'session/close', first)
        call(10, 'session/close', second)
        captured = [json.loads(line) for line in records.read_text(encoding='utf-8').splitlines()]
        started = [row['pid'] for row in captured if row['kind'] == 'started']
        closed = [row['pid'] for row in captured if row['kind'] == 'closed']
        called = [row['pid'] for row in captured if row['kind'] == 'called']
        if len(set(started)) != 3 or set(started) != set(closed) or len(called) != 3:
            raise RuntimeError('ACP stdio children were not independently consumed and closed')
        if not all(process_exited(identity) for identity in started):
            raise RuntimeError('ACP stdio child remains alive after awaited close')
        if any(row['cwd'] != str(workspace) or row['token'] != 'session-owned' for row in captured):
            raise RuntimeError('ACP stdio workspace/environment ownership differs')
        http_records = workspace / 'http-records.json'
        http = subprocess.Popen([sys.executable, str(SCRIPT_ROOT / 'oracles/mcp_http_peer.py'), 'session', str(http_records)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        url = http.stdout.readline().decode('utf-8').strip()
        web = call(11, 'session/new', {'cwd': str(workspace), 'mcpServers': [{
            'type': 'http', 'name': 'fixture', 'url': url,
            'headers': [{'name': 'Authorization', 'value': 'session-owned'}]}]})
        prompt(12, web, 'HTTP consumer')
        call(13, 'session/close', web)
        peer.finish()
        http.stdin.close()
        if http.wait(timeout=5) != 0 or http.stderr.read():
            raise RuntimeError('ACP HTTP fixture did not close cleanly')
        http_rows = json.loads(http_records.read_text(encoding='utf-8'))
        if not http_rows or any(row['headers'].get('authorization') != 'session-owned' for row in http_rows):
            raise RuntimeError('ACP HTTP headers were not forwarded')
        if len(requests) != 8 or any('mcp__fixture__echo' not in [tool['function']['name'] for tool in request.get('tools', [])]
                                      for request in requests):
            raise RuntimeError('Actual model consumers did not receive the session tool')
        if any('actual ACP MCP consumer' not in str(request['messages']) for request in requests[1::2]):
            raise RuntimeError('Actual model continuation did not receive the MCP result')
        return {'stdioProcesses': 3, 'stdioCalls': 3, 'stdioReaped': True, 'httpCalls': 1, 'httpClosed': True,
                'acpClosed': True, 'modelRequests': 8, 'scope': 'Actual canonical ACP process, stdio/HTTP consumers and same-session resume; no external endpoint.'}
    finally:
        if peer is not None:
            peer.close()
        if http is not None:
            if http.poll() is None:
                http.kill()
            http.wait(timeout=5)
            for stream in (http.stdin, http.stdout, http.stderr):
                stream.close()
        server.shutdown()
        server.server_close()
        thread.join(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=True)
    try:
        value = journey(args.root.resolve(), args.workspace.resolve())
        report = {'result': 'passed', 'value': value}
    except Exception as error:
        report = {'result': 'failed', 'error': str(error)}
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report['result'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
