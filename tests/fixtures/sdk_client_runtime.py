"""Keyless wire peer for native SDK client integration tests (Python 3.8)."""
import json
import os
from pathlib import Path
import sys
import time
sys.stdout.reconfigure(encoding='utf-8')
sys.stdin.reconfigure(encoding='utf-8')


def write(value):
    print(json.dumps(dict(jsonrpc='2.0', **value), ensure_ascii=False), flush=True)


def notify(method, params):
    write(dict(method=method, params=params))


if os.environ.get('STDERR'):
    sys.stderr.write(os.environ['STDERR']); sys.stderr.flush()
cwd = os.getcwd()
for line in sys.stdin:
    frame = json.loads(line); identity, method, params = frame.get('id'), frame.get('method'), frame.get('params', {})
    if method == 'initialize':
        if os.environ.get('RECORD_INIT'):
            Path(os.environ['RECORD_INIT']).write_text(json.dumps(params), encoding='utf-8')
        marker = os.environ.get('FAIL_ONCE')
        if marker and not Path(marker).exists():
            Path(marker).write_text('failed', encoding='utf-8')
            write(dict(id=identity, error=dict(code=7, message='init failure'))); continue
        if os.environ.get('HANG_INIT'):continue
        cwd = params['cwd']
        result = dict(serverInfo=dict(name='scripted-native-peer', version='1'))
    elif method == 'shutdown':
        if os.environ.get('IGNORE_SHUTDOWN'):continue
        write(dict(id=identity, result={})); break
    elif method == 'session/working-directory/set':
        cwd = os.path.abspath(os.path.join(cwd, params['path'])); result = dict(cwd=cwd)
    elif method == 'session/working-directory/get':result = dict(cwd=cwd)
    elif method == 'session/prompt':
        if os.environ.get('PROMPT_READY'):Path(os.environ['PROMPT_READY']).write_text('ready', encoding='utf-8')
        if os.environ.get('HANG_PROMPT'):continue
        session = params['sessionId']
        def event(kind, data):notify('session.event', dict(sessionId=session, event=dict(type=kind, data=data)))
        event('assistant/message', dict(message=dict(content=[dict(type='text', text='wire answer')]), stream=[]))
        event('turn/end', dict(reason=dict(kind='completed')))
        result = dict(messageId='message-1')
    elif method == 'session/wait':result = {}
    elif method == 'notifications':
        notify('subagent.started', dict(parentSessionId='root', childSessionId='child'))
        notify('session.event', dict(sessionId='child', event=dict(type='future')))
        notify('session.event', dict(sessionId='other', event=dict(type='future')))
        result = {}
    elif method == 'hang':continue
    else:
        write(dict(id=identity, error=dict(code=-32601, message='unknown method'))); continue
    write(dict(id=identity, result=result))
if os.environ.get('IGNORE_EOF'):
    while True:time.sleep(.1)
