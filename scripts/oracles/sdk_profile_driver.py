import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def read_session_logs(home):
    absolute = os.path.abspath(str(home))
    if os.name == 'nt' and not absolute.startswith('\\\\?\\'):
        absolute = '\\\\?\\UNC\\' + absolute[2:] if absolute.startswith('\\\\') else '\\\\?\\' + absolute
    physical = Path(absolute)
    return {path.relative_to(physical).as_posix(): path.read_text(encoding='utf-8')
            for path in (physical / 'sessions').rglob('*.jsonl')}


def run(side, scenario, options, destination):
    phase = destination / (options.native_label if side == 'native' else 'source')
    phase.mkdir()
    home = phase / 'home'
    profile = home / 'profiles/minimal'
    profile.mkdir(parents=True)
    with (profile / 'package.json').open('x', encoding='utf-8') as stream:
        json.dump(dict(name='sdk-profile-probe', private=True, type='module',
            dsh=dict(profile=dict(bundles=['@deepseek-ai/dsh-sdk-minimal'], patchReload='startup'))), stream, indent=2)
        stream.write('\n')
    requests, observed, errors, fixture_errors = [], [], [], []
    released = threading.Event()
    stopping = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *arguments):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            if scenario == 'normal' and len(requests) == 1:
                chunk = dict(choices=[dict(delta=dict(tool_calls=[dict(index=0, id='minimal-shell-call', type='function',
                    function=dict(name='pwsh', arguments=json.dumps(dict(command="Write-Output ('SDK' + '_TOOL_ROUND_TRIP')"), separators=(',', ':'))))]), finish_reason='tool_calls')])
            elif scenario == 'normal':
                chunk = dict(choices=[dict(delta=dict(content='SDK_FINAL'), finish_reason='stop')], usage=dict(prompt_tokens=10, completion_tokens=2))
            else:
                chunk = dict(choices=[dict(delta=dict(content='SDK_PENDING' if scenario == 'cancel' else 'SDK_PARTIAL_ERROR'), finish_reason=None)])
            payload = ('data: ' + json.dumps(chunk, separators=(',', ':')) + '\n\n' + ('data: [DONE]\n\n' if scenario == 'normal' else '')).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            if scenario != 'cancel':
                self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.wfile.flush()
            if scenario == 'cancel':
                released.wait(30)
            self.close_connection = True

    class Server(ThreadingHTTPServer):
        daemon_threads = False

        def handle_error(self, request, client_address):
            exception = sys.exc_info()[1]
            fixture_errors.append(dict(name=type(exception).__name__, message=str(exception),
                winerror=getattr(exception, 'winerror', None), shutdown_requested=stopping.is_set(),
                requests=len(requests)))
            super().handle_error(request, client_address)

    server = Server(('127.0.0.1', 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    native_receipt = phase / 'runtime.json'
    environment = {name: value for name, value in os.environ.items()
        if name.upper() not in ('DSH_HOME', 'PYTHONPATH', 'PYTHONHOME') and not name.upper().endswith(('API_KEY', 'API_TOKEN', 'ACCESS_TOKEN', 'REFRESH_TOKEN', 'OAUTH_TOKEN'))}
    environment.update(DSH_HOME=str(home), DSH_TELEMETRY_DISABLED='1', DEEPSEEK_API_KEY='controlled-local-fixture',
        DEEPSEEK_BASE_URL='http://127.0.0.1:' + str(server.server_port), DSH_SDK_NATIVE_ROOT=str(options.native_root),
        DSH_SDK_SOURCE_ROOT=str(options.source_root), DSH_SDK_RUNTIME_OUTPUT=str(native_receipt),
        TSX_TSCONFIG_PATH=str(options.source_root / 'tsconfig.json'))
    observers = Path(__file__).resolve().parent
    if side == 'source':
        command = [shutil.which('node'), '--import', (options.source_root / 'node_modules/tsx/dist/esm/index.mjs').as_uri(),
            str(observers / 'sdk_profile_source.mts'), '--profile', 'minimal']
    else:
        command = [str(options.native_python or sys.executable), '-I', str(observers / 'sdk_profile_python.py'), '--profile', 'minimal']
    process = subprocess.Popen(command, cwd=str(destination), env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, encoding='utf-8', errors='strict', bufsize=1)
    frames = queue.Queue()

    def read():
        for line in process.stdout:
            try:
                frames.put(json.loads(line))
            except ValueError:
                frames.put(dict(invalid=line))
        frames.put(dict(eof=True))

    reader = threading.Thread(target=read, daemon=True)
    error_reader = threading.Thread(target=lambda: errors.append(process.stderr.read()), daemon=True)
    reader.start()
    error_reader.start()
    deadline = time.monotonic() + 90

    def wait(predicate):
        while True:
            frame = frames.get(timeout=max(0.001, deadline - time.monotonic()))
            observed.append(frame)
            if 'eof' in frame or 'invalid' in frame:
                raise ValueError('Invalid SDK runtime output: ' + repr(frame))
            if predicate(frame):
                return frame

    def send(identity, method, params):
        process.stdin.write(json.dumps(dict(jsonrpc='2.0', id=identity, method=method, params=params)) + '\n')
        process.stdin.flush()

    result = dict(side=side, scenario=scenario, requests=requests, frames=observed, startedAt=int(time.time() * 1000))
    try:
        send(1, 'initialize', dict(cwd=str(destination), provider='deepseek-official', model='deepseek-v4-pro'))
        initialized = wait(lambda frame: frame.get('id') == 1)
        if 'result' not in initialized:
            raise ValueError('SDK initialization failed: ' + repr(initialized))
        send(2, 'session/prompt', dict(sessionId='minimal-controlled', contentBlocks=[dict(type='text', text='Run the controlled local tool.')]))
        wait(lambda frame: frame.get('id') == 2)
        if scenario == 'cancel':
            wait(lambda frame: frame.get('method') == 'session.event' and frame.get('params', {}).get('event', {}).get('data', {}).get('chunk', {}).get('text') == 'SDK_PENDING')
        else:
            wait(lambda frame: frame.get('method') == 'session.event' and frame.get('params', {}).get('event', {}).get('type') == 'turn/end')
        stopping.set()
        send(3, 'shutdown', {})
        wait(lambda frame: frame.get('id') == 3)
        result['exitCode'] = process.wait(timeout=20)
        if result['exitCode'] != 0 or len(requests) != (2 if scenario == 'normal' else 1):
            raise ValueError('SDK request chain did not drain and exit')
        if scenario == 'normal' and 'SDK_TOOL_ROUND_TRIP' not in json.dumps(requests[1]):
            raise ValueError('Real shell result missing from next model request')
    except Exception as error:
        result['failure'] = dict(name=type(error).__name__, message=str(error))
    finally:
        released.set()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        reader.join(2)
        error_reader.join(2)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        server.shutdown()
        server.server_close()
        serving.join(2)
        result['endedAt'] = int(time.time() * 1000)
        result['stderr'] = ''.join(errors)
        result['fixtureErrors'] = fixture_errors
        result['command'] = command
        result['logs'] = read_session_logs(home)
        if side == 'native' and native_receipt.exists():
            result['runtime'] = json.loads(native_receipt.read_text(encoding='utf-8'))
        with (phase / 'capture.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--native-root', type=Path, required=True)
    parser.add_argument('--native-python', type=Path)
    parser.add_argument('--source-receipt', type=Path)
    parser.add_argument('--native-label', default='native')
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    options.source_root = options.source_root.resolve()
    options.native_root = options.native_root.resolve()
    options.output = options.output.resolve()
    if not options.native_label or '/' in options.native_label or '\\' in options.native_label or options.native_label in ('.', '..', 'source'):
        raise ValueError('Fresh native phase label required')
    retained_source = None
    if options.source_receipt:
        retained_source = json.loads(options.source_receipt.read_text(encoding='utf-8'))
    else:
        destination = options.output.with_suffix('.files')
        destination.mkdir(parents=True)
        assert subprocess.check_output(['node', '--version'], encoding='utf-8').strip() == 'v22.22.2'
    captures = {}
    for scenario in ('normal', 'cancel', 'error'):
        if retained_source is None:
            scenario_destination = destination / scenario
            scenario_destination.mkdir()
            captures[scenario] = {side: run(side, scenario, options, scenario_destination) for side in ('source', 'native')}
        else:
            scenario_destination = Path(retained_source['destinations'][scenario])
            captures[scenario] = dict(source=retained_source['captures'][scenario],
                native=run('native', scenario, options, scenario_destination))
        print(json.dumps(dict(scenario=scenario, frames={side: len(capture['frames']) for side, capture in captures[scenario].items()})), flush=True)
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(captures=captures), stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    return 1 if any(capture.get('failure') for group in captures.values() for capture in group.values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
