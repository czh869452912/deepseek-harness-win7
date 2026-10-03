import argparse
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from acp_permission_journey import Peer
from acp_mcp_journey import process_exited


def prepare_profiles(root, workspace, endpoint):
    sys.path.insert(0, str(root))
    from dsh.boot.profile import init_profile
    import yaml
    home = workspace / 'home'
    pid_path = workspace / 'actual-child-pid.txt'
    wrapper = ('import os,runpy,sys;from pathlib import Path;'
        'Path({}).write_text(str(os.getpid()),encoding="utf-8");'
        'sys.path.insert(0,{});sys.argv=[{},"--profile","child-acp"];runpy.run_path({},run_name="__main__")').format(
            repr(str(pid_path)), repr(str(root)), repr(str(root / 'dsh.py')), repr(str(root / 'dsh.py')))
    for name in ('acp', 'child-acp'):
        profile = home / 'profiles' / name
        init_profile(str(profile), [], 'startup')
        rows = [{'id': package, 'name': '@deepseek-ai/dsh-' + package} for package in
            ('session', 'tools', 'system-prompt', 'llm', 'llm-deepseek', 'credentials-local',
             'agent', 'agent-loop', 'acp-app')]
        rows += [{'id': 'acp', 'name': '@deepseek-ai/dsh-acp', 'inject': ['acpAppStartup'],
            'config': {'provider': 'deepseek-official', 'model': 'deepseek-v4-flash' if name == 'acp' else 'deepseek-v4-pro'}},
            {'id': 'persistence', 'name': '@deepseek-ai/dsh-session-persistence-jsonl',
             'config': {'root': str(workspace / (name + '-sessions')), 'packChunks': False}}]
        if name == 'acp':
            rows += [{'id': package, 'name': '@deepseek-ai/dsh-' + package} for package in ('subprocess-local', 'subagent')]
            rows += [{'id': 'subagent-acp', 'name': '@deepseek-ai/dsh-subagent-acp', 'config': {
                'command': sys.executable, 'args': (['-I'] if (root / 'python.exe').is_file() else []) + ['-u', '-c', wrapper],
                'env': {'DSH_HOME': str(home), 'DSH_TELEMETRY_MODE': 'DISABLED',
                        'DEEPSEEK_API_KEY': 'fixture-only', 'DEEPSEEK_BASE_URL': endpoint}}},
                {'id': 'tool-subagent', 'name': '@deepseek-ai/dsh-tool-subagent', 'config': {
                    'provider': 'acp', 'maxDepth': 'provider-managed', 'enableRunInBackground': False}}]
        else:
            rows += [{'id': 'fs', 'name': '@deepseek-ai/dsh-fs-local', 'config': {'cwd': str(workspace)}},
                {'id': 'editor', 'name': '@deepseek-ai/dsh-tool-str-replace-editor'}]
        (profile / 'cordis.patch.yml').write_text(yaml.safe_dump([{'insert': rows}]), encoding='utf-8')
    return home, pid_path


def journey(root, workspace):
    requests = []
    output_file = workspace / 'child-owned-file.txt'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            continuation = any(message['role'] == 'tool' for message in request['messages'])
            parent = request['model'] == 'deepseek-v4-flash'
            if continuation:
                delta = {'content': 'parent received child result' if parent else 'actual child completed file work'}
            else:
                arguments = {'description': 'actual ACP child', 'prompt': 'explicit child file task'} if parent else {
                    'command': 'create', 'path': str(output_file), 'file_text': 'created by actual ACP child'}
                delta = {'tool_calls': [{'index': 0, 'id': 'parent-delegation' if parent else 'child-file-tool',
                    'type': 'function', 'function': {'name': 'subagent' if parent else 'str_replace_editor',
                        'arguments': json.dumps(arguments)}}]}
            body = ('data: ' + json.dumps({'choices': [{'delta': delta,
                'finish_reason': 'stop' if continuation else 'tool_calls'}]}) + '\n\ndata: [DONE]\n\n').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    peer = None
    try:
        endpoint = 'http://127.0.0.1:%s' % server.server_port
        home, pid_path = prepare_profiles(root, workspace, endpoint)
        peer = Peer(root, workspace, home, endpoint)
        def call(identity, method, params):
            peer.request(identity, method, params)
            packet = peer.reply(identity)
            if 'error' in packet:
                raise RuntimeError('ACP subagent journey failed: ' + json.dumps(packet))
            return packet['result']
        call(1, 'initialize', {'protocolVersion': 1})
        created = call(2, 'session/new', {'cwd': str(workspace), 'mcpServers': []})
        result = call(3, 'session/prompt', dict(created, prompt=[{'type': 'text', 'text': 'private parent instruction, delegate the explicit task'}]))
        if result != {'stopReason': 'end_turn'}:
            raise RuntimeError('Parent ACP prompt did not complete: ' + repr(result))
        if output_file.read_text(encoding='utf-8') != 'created by actual ACP child':
            raise RuntimeError('Actual child file tool was not consumed')
        child_pid = int(pid_path.read_text(encoding='utf-8'))
        if not process_exited(child_pid):
            raise RuntimeError('Actual ACP child was not reaped before the parent tool returned')
        parent_requests = [request for request in requests if request['model'] == 'deepseek-v4-flash']
        child_requests = [request for request in requests if request['model'] == 'deepseek-v4-pro']
        if len(parent_requests) != 2 or len(child_requests) != 2:
            raise RuntimeError('Actual parent/child model chain did not execute four requests')
        if 'actual child completed file work' not in str(parent_requests[-1]['messages']):
            raise RuntimeError('Parent model continuation did not receive the actual ACP child result')
        if any('private parent instruction' in str(request['messages']) for request in child_requests):
            raise RuntimeError('Parent context leaked into the ACP child')
        if 'created by actual ACP child' not in str(child_requests[-1]['messages']):
            raise RuntimeError('Child model continuation did not receive the actual file result')
        call(4, 'session/close', created)
        peer.finish()
        (workspace / 'model-requests.json').write_text(json.dumps(requests, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        return {'parentRequests': 2, 'childRequests': 2, 'fileWork': True, 'childReaped': True,
            'parentContextIsolated': True, 'parentClosed': True,
            'scope': 'Actual canonical parent ACP, subprocess ACP child and file/model consumers; local endpoint only.'}
    finally:
        (workspace / 'model-requests.json').write_text(json.dumps(requests, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        if peer is not None:
            (workspace / 'parent-frames.json').write_text(json.dumps(peer.observed, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
            peer.close()
            (workspace / 'parent-stderr.json').write_text(json.dumps(peer.errors, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
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
