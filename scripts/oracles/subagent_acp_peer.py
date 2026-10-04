import json
import os
from pathlib import Path
import sys
import time


sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')


def send(packet):
    sys.stdout.write(json.dumps(dict(jsonrpc='2.0', **packet), ensure_ascii=True) + '\n')
    sys.stdout.flush()


def record(packet):
    destination = os.environ.get('PROBE_RECORD')
    if destination:
        with open(destination, 'a', encoding='utf-8') as output:
            output.write(json.dumps(packet, ensure_ascii=True) + '\n')


def response(identity, result):
    send({'id': identity, 'result': result})


def answer_prompt(packet):
    identity, params = packet['id'], packet['params']
    if os.environ.get('PROBE_THOUGHT') == '1':
        send({'method': 'session/update', 'params': {'sessionId': params['sessionId'],
              'update': {'sessionUpdate': 'agent_thought_chunk', 'content': {'type': 'text', 'text': 'private thought'}}}})
    content = os.environ.get('PROBE_TEXT', 'child answer')
    if os.environ.get('PROBE_ECHO_CWD') == '1':
        content = os.getcwd() + '\n' + session_cwd
    if os.environ.get('PROBE_ECHO_ENV'):
        name = os.environ['PROBE_ECHO_ENV']
        content = os.environ.get(name, '<' + name + ' unset>')
    for text in (content[:len(content) // 2], content[len(content) // 2:]):
        send({'method': 'session/update', 'params': {'sessionId': params['sessionId'],
              'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': text}}}})
    if os.environ.get('PROBE_CRASH_AFTER_CHUNK') == '1':
        os._exit(17)
    if os.environ.get('PROBE_HANG') == '1':
        send({'id': 'stream-admitted', 'method': 'session/request_permission', 'params': {
            'sessionId': 'same-child-id', 'toolCall': {'toolCallId': 'barrier', 'title': 'admission', 'kind': 'think'},
            'options': [{'kind': 'reject_once', 'optionId': 'no', 'name': 'admission'}]}})
        return
    response(identity, {'stopReason': os.environ.get('PROBE_STOP', 'end_turn')})


session_cwd, prompt_packet = None, None
record({'spawn': {'pid': os.getpid(), 'cwd': os.getcwd()}})
for line in sys.stdin:
    packet = json.loads(line)
    record(packet)
    method = packet.get('method')
    if method == 'initialize':
        if os.environ.get('PROBE_CRASH_INITIALIZE') == '1':
            os._exit(11)
        response(packet['id'], {'protocolVersion': 1, 'agentCapabilities': {}, 'authMethods': []})
    elif method == 'session/new':
        session_cwd = packet['params']['cwd']
        ready = os.environ.get('PROBE_NEW_READY')
        if ready:
            Path(ready).write_text('ready', encoding='utf-8')
            while not Path(os.environ['PROBE_NEW_GO']).exists():
                time.sleep(0.01)
        response(packet['id'], {} if os.environ.get('PROBE_MISSING_ID') == '1' else {'sessionId': 'same-child-id'})
    elif method == 'session/prompt':
        prompt_packet = packet
        if os.environ.get('PROBE_PERMISSION') == '1':
            options = [{'kind': 'reject_once', 'optionId': 'no', 'name': 'untrusted credential text'}]
            if os.environ.get('PROBE_NO_ALLOW') != '1':
                options += [{'kind': 'allow_always', 'optionId': 'first', 'name': 'untrusted title'},
                            {'kind': 'allow_once', 'optionId': 'second', 'name': 'untrusted path'}]
            tool_call = {'toolCallId': 'child-tool', 'title': 'untrusted path secret'}
            if os.environ.get('PROBE_TOOL_KIND'):
                tool_call['kind'] = os.environ['PROBE_TOOL_KIND']
            send({'id': 'permission', 'method': 'session/request_permission',
                  'params': {'sessionId': 'same-child-id', 'options': options, 'toolCall': tool_call}})
        else:
            answer_prompt(packet)
    elif packet.get('id') == 'permission' and 'result' in packet:
        denied = packet['result']['outcome']['outcome'] == 'cancelled'
        if denied and os.environ.get('PROBE_IGNORE_PERMISSION') != '1':
            response(prompt_packet['id'], {'stopReason': 'cancelled'})
        else:
            answer_prompt(prompt_packet)
    elif packet.get('id') == 'stream-admitted' and 'result' in packet:
        ready = os.environ.get('PROBE_READY')
        if ready:
            Path(ready).write_text('ready', encoding='utf-8')
    elif method == 'session/cancel':
        if os.environ.get('PROBE_IGNORE_CANCEL') != '1' and prompt_packet is not None:
            response(prompt_packet['id'], {'stopReason': 'cancelled'})
if os.environ.get('PROBE_IGNORE_EOF') == '1':
    while True:
        time.sleep(1)
if os.environ.get('PROBE_FLUSH'):
    time.sleep(0.08)
    Path(os.environ['PROBE_FLUSH']).write_text('flushed', encoding='utf-8')
record({'closed': True})
