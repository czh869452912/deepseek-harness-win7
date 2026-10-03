import json
from pathlib import Path
import sys


mode, observation_path = sys.argv[1:3]
observations = []
pending = []


def record(direction, packet):
    observations.append({'direction': direction, 'packet': packet})
    Path(observation_path).write_text(json.dumps(observations, ensure_ascii=False), encoding='utf-8')


def send(packet):
    record('sent', packet)
    sys.stdout.buffer.write((json.dumps(packet, ensure_ascii=False) + '\n').encode('utf-8'))
    sys.stdout.buffer.flush()


for line in sys.stdin.buffer:
    packet = json.loads(line)
    record('received', packet)
    method = packet.get('method')
    if method == 'tools/call':
        Path(observation_path + '.admitted').touch()
    if 'id' not in packet:
        continue
    if method is None:
        continue
    reply = {'jsonrpc': '2.0', 'id': packet['id']}
    if mode == 'id-decimal':
        reply['id'] = str(packet['id'])
    if mode == 'id-hex':
        reply['id'] = hex(packet['id'])
    if mode == 'id-empty' and method == 'initialize':
        reply['id'] = ''
    if method == 'initialize':
        reply['result'] = {'protocolVersion': 'unsupported' if mode == 'unsupported' else '2025-11-25',
                           'capabilities': {} if mode == 'capabilities-empty' else {'tools': {}},
                           'serverInfo': {'name': 'controlled', 'version': '1.0'}}
        if mode == 'cap-logging-array':
            reply['result']['capabilities']['logging'] = []
        if mode == 'cap-experimental-false':
            reply['result']['capabilities']['experimental'] = {'extension': False}
    elif method == 'tools/list':
        if mode == 'notification':
            send({'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'})
        reply['result'] = {'tools': [{'name': 'echo', 'inputSchema': {'type': 'object'}}]}
        if mode == 'tool-annotations-false':
            reply['result']['tools'][0]['annotations'] = False
        if mode == 'tool-properties-array':
            reply['result']['tools'][0]['inputSchema']['properties'] = {'value': []}
        if mode == 'tool-unknown':
            reply['result']['tools'][0]['unknown'] = {'preserveOnlyRawFrame': True}
    elif method == 'tools/call':
        if mode == 'eof':
            break
        if mode in ('cancel', 'timeout'):
            continue
        if mode in ('peer-error', 'peer-error-null'):
            reply['error'] = {'code': -32602, 'message': 'controlled rejection',
                              'data': None if mode == 'peer-error-null' else {'invalid': True}}
        else:
            reply['result'] = {'content': [{'type': 'text', 'text': packet['params']['arguments']['text']}]}
            if mode == 'out-of-order':
                pending.append(reply)
                if len(pending) == 3:
                    for response in reversed(pending):
                        send(response)
                continue
    else:
        reply['result'] = {}
    if mode == 'malformed-then-valid':
        send(dict(reply, extra=True))
    send(reply)
