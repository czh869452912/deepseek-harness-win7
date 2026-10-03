import argparse
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading


def journey(root, workspace):
    steps = []
    session_id = None
    for iteration in range(2):
        child = subprocess.Popen([sys.executable, '-I', '-u', str(root / 'dsh.py'), '--profile', 'acp'],
            cwd=str(workspace), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding='utf-8', bufsize=1)
        frames, errors = queue.Queue(), []
        def read():
            for line in child.stdout:
                try:
                    frames.put(json.loads(line))
                except ValueError:
                    frames.put({'invalid': line})
            frames.put({'eof': True})
        reader = threading.Thread(target=read, daemon=True)
        stderr = threading.Thread(target=lambda: errors.append(child.stderr.read()), daemon=True)
        reader.start()
        stderr.start()
        def request(identity, method, params):
            child.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params}) + '\n')
            child.stdin.flush()
            frame = frames.get(timeout=10)
            if frame.get('id') != identity or frame.get('jsonrpc') != '2.0':
                raise RuntimeError('Unexpected ACP frame: ' + repr(frame))
            return frame
        try:
            initialized = request(1, 'initialize', {'protocolVersion': 1})
            if initialized.get('result', {}).get('protocolVersion') != 1:
                raise RuntimeError('ACP initialize failed')
            steps.append('initialize-' + str(iteration))
            if iteration == 0:
                invalid = request(2, 'session/new', {'cwd': str(workspace)})
                if invalid.get('error', {}).get('code') != -32602:
                    raise RuntimeError('Missing MCP parameter admitted')
                created = request(3, 'session/new', {'cwd': str(workspace), 'mcpServers': []})
                session_id = created['result']['sessionId']
                steps.extend(['invalid-params-before-effects', 'persistent-new'])
            else:
                resumed = request(3, 'session/resume', {'sessionId': session_id, 'cwd': str(workspace)})
                if 'configOptions' not in resumed.get('result', {}):
                    raise RuntimeError('ACP durable resume failed')
                steps.append('new-process-resume-no-history-updates')
            if request(4, 'session/close', {'sessionId': session_id}).get('result') != {}:
                raise RuntimeError('ACP close failed')
            listed = request(5, 'session/list', {})
            if listed.get('result', {}).get('sessions') != [{'sessionId': session_id, 'cwd': str(workspace)}]:
                raise RuntimeError('ACP durable list lost identity')
            steps.append('close-list-' + str(iteration))
            child.stdin.close()
            if child.wait(timeout=10) != 0:
                raise RuntimeError('ACP EOF failed')
            reader.join(2)
            stderr.join(2)
            if errors != [''] or frames.get(timeout=1) != {'eof': True}:
                raise RuntimeError('ACP late output or stderr: ' + repr(errors))
            steps.append('eof-' + str(iteration))
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=3)
            reader.join(2)
            stderr.join(2)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
    return {'steps': steps, 'sessionId': session_id, 'processes': 2}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({'result': 'passed', 'value': journey(args.root.resolve(), args.workspace.resolve())}))


if __name__ == '__main__':
    main()
