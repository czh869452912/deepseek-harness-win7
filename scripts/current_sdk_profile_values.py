import copy
import hashlib
import json
from pathlib import Path

from scripts.canonical_llm_values import observation_digest as value_digest
from scripts.sdk_profile_cases import SCENARIOS
from scripts.import_paths import resolve_import_path


FRAME_COUNTS = dict(normal=25, cancel=15, error=19)
REPLY_POSITIONS = dict(normal=[0, 5, 24], cancel=[0, 5, 14], error=[0, 5, 18])
IMPORTS = json.loads(Path(__file__).with_name('current_sdk_profile_imports.json').read_text(encoding='utf-8'))
OPTIONAL_CANCEL_IMPORT = 'dsh/llm/adapter_failure.py'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public(capture, scenario, destination):
    if capture.get('failure') or type(capture.get('exitCode')) is not int or capture['exitCode'] != 0 or capture.get('stderr'):
        raise ValueError('SDK outcome or diagnostics differ')
    if capture.get('scenario') != scenario or len(capture['requests']) != (2 if scenario == 'normal' else 1):
        raise ValueError('SDK selected request chain differs')
    fixture_errors = capture.get('fixtureErrors')
    if not isinstance(fixture_errors, list) or fixture_errors and (capture['side'] != 'source' or scenario != 'cancel' or len(fixture_errors) != 1):
        raise ValueError('SDK owned HTTP fixture outcome differs')
    for error in fixture_errors:
        if (set(error) != {'name', 'message', 'winerror', 'shutdown_requested', 'requests'}
                or error['name'] != 'ConnectionResetError' or type(error['winerror']) is not int or error['winerror'] != 10054
                or error['shutdown_requested'] is not True or type(error['requests']) is not int or error['requests'] != 1
                or not isinstance(error['message'], str) or not error['message']):
            raise ValueError('SDK owned shutdown fixture diagnostic differs')
    frames = copy.deepcopy(capture['frames'])
    if len(frames) != FRAME_COUNTS[scenario] or [index for index, frame in enumerate(frames) if 'id' in frame] != REPLY_POSITIONS[scenario]:
        raise ValueError('Complete SDK frame count or interleaving differs')
    replies = [frame for frame in frames if 'id' in frame]
    if [frame['id'] for frame in replies] != [1, 2, 3] or any(set(frame) != {'jsonrpc', 'id', 'result'} or frame['jsonrpc'] != '2.0' for frame in replies):
        raise ValueError('SDK initialize/prompt/shutdown replies differ')
    notifications = [frame for frame in frames if 'id' not in frame]
    if any(set(frame) != {'jsonrpc', 'method', 'params'} or frame['jsonrpc'] != '2.0' or frame['params'].get('sessionId') != 'minimal-controlled' for frame in notifications):
        raise ValueError('SDK notification carrier differs')
    events = [frame['params']['event'] for frame in notifications if frame['method'] == 'session.event']
    statuses = [frame['params']['status'] for frame in notifications if frame['method'] == 'session.status']
    count = dict(normal=20, cancel=11, error=14)[scenario]
    if [event['seq'] for event in events] != list(range(count)) or statuses != (['running'] if scenario == 'cancel' else ['running', 'idle']):
        raise ValueError('SDK event sequence or lifecycle differs')
    if len(capture['logs']) != 1:
        raise ValueError('One SDK-owned durable session required')
    log_name, payload = next(iter(capture['logs'].items()))
    lines = [json.loads(line) for line in payload.splitlines()]
    expected_events = copy.deepcopy(events)
    if scenario == 'cancel':
        if len(lines) != 15 or lines[1:12] != expected_events or [event['seq'] for event in lines[1:]] != list(range(14)):
            raise ValueError('Complete cancelled durable facts differ')
        partial = lines[12]
        if partial['type'] != 'assistant/message' or partial['data'].get('interrupted') is not True:
            raise ValueError('Cancelled partial-message marker differs')
        message = partial['data']['message']
        if message['source'] != dict(kind='model', provider='deepseek-official', model='deepseek-v4-pro') or message['content'] != [dict(type='text', text='SDK_PENDING')]:
            raise ValueError('Cancelled partial-message route/content/causality differs')
        stream = partial['data']['stream']
        if (len(stream) != 2 or stream[0].get('chunk') != dict(type='block-start', index=0, blockType='text')
                or stream[1] != dict(type='text-chunks', time0=stream[1].get('time0'), index=0, dt=[], texts=['SDK_PENDING'])):
            raise ValueError('Cancelled partial stream differs')
        barrier = copy.deepcopy(capture.get('liveBarrier'))
        if barrier != dict(sessionId='minimal-controlled', frame=dict(type='chunk', attemptId='minimal-controlled:1',
                revision=3, index=1, time=stream[1]['time0'], chunk=dict(type='text-delta', index=0, text='SDK_PENDING'))):
            raise ValueError('Actual pending-stream admission barrier differs')
        if lines[-2]['type'] != 'step/end' or lines[-1]['type'] != 'turn/end' or lines[-1]['data']['reason'] != dict(kind='aborted', reason=dict(kind='disposed')):
            raise ValueError('Cancellation terminal facts differ')
    else:
        barrier = None
        if capture.get('liveBarrier') is not None:
            raise ValueError('Unexpected pending-stream admission barrier')
        if len(lines) != count + 1 or lines[1:] != expected_events:
            raise ValueError('Complete durable facts differ from emitted facts')
        if scenario == 'error':
            if any(event['type'] == 'assistant/message' for event in events):
                raise ValueError('Ordinary stream error incorrectly persists an interrupted assistant')
            if events[-1]['type'] != 'turn/end' or events[-1]['data']['reason'] != dict(kind='error', error=dict(message='DeepSeek Messages stream ended before message_stop', code='STREAM_CLOSED')):
                raise ValueError('Full typed stream failure differs')
    header = lines[0]
    if (set(header) != {'type', 'version', 'id', 'createdAt', 'cwd', 'isSeeded', 'delegationDepth'}
            or header['type'] != 'session' or type(header['version']) is not int or header['version'] != 4
            or header['isSeeded'] is not False or header['id'] != 'minimal-controlled' or header['cwd'] != str(destination)):
        raise ValueError('SDK durable header identity differs')
    start, end = capture['startedAt'], capture['endedAt']
    times = [event['time'] for event in lines[1:]]
    if type(start) is not int or type(end) is not int or not 0 <= end - start <= 90000 or times != sorted(times) or any(type(value) is not int or not start <= value <= end for value in times):
        raise ValueError('Actual SDK clock window/order differs')
    if type(header['createdAt']) is not int or not start <= header['createdAt'] <= times[0]:
        raise ValueError('Actual SDK creation clock differs')
    requests = copy.deepcopy(capture['requests'])
    previous = -1
    uploaded = []
    for request in requests:
        delivery = request['dsh_session_log']
        if (set(delivery) != {'version', 'sessionFormatVersion', 'session', 'afterSeq', 'throughSeq', 'events'}
                or delivery['version'] != 1 or delivery['sessionFormatVersion'] != 4
                or delivery['session'] != {key: header[key] for key in ('version', 'id', 'createdAt', 'cwd')}
                or type(delivery['afterSeq']) is not int or delivery['afterSeq'] != previous
                or type(delivery['throughSeq']) is not int or not previous < delivery['throughSeq'] < len(lines)-1
                or delivery['events'] != lines[previous+2:delivery['throughSeq']+2]):
            raise ValueError('SDK Messages upload differs from the exact durable interval')
        previous = delivery['throughSeq']
        delivery['session']['createdAt'] = ['validated-live-clock', 'creation']
        uploaded.extend(delivery['events'])
    # Validate real compact-stream clocks before assigning typed observation aliases.
    # Raw captures retain every timestamp; duration deltas and all chunk fields stay compared.
    for event in events + lines[1:] + uploaded:
        last = start
        for index, entry in enumerate(event.get('data', {}).get('stream', [])):
            field = 'time' if entry.get('type') == 'chunk' else 'time0'
            value = entry[field]
            if type(value) is not int or not last <= value <= event['time']:
                raise ValueError('Actual compact stream clock window/order differs')
            last = value
            if field == 'time0':
                deltas = entry['dt']
                if not isinstance(deltas, list) or any(type(delta) is not int or delta < 0 for delta in deltas):
                    raise ValueError('Actual compact stream delta clock differs')
                last += sum(deltas)
                if last > event['time']:
                    raise ValueError('Actual compact stream delta exceeds durable fact')
            entry[field] = ['validated-live-clock', event['seq'], 'stream', index]
        event['time'] = ['validated-live-clock', event['seq']]
    if barrier is not None:
        barrier['frame']['time'] = ['validated-live-clock', 11, 'stream', 1]
    header['createdAt'] = ['validated-live-clock', 'creation']
    return dict(group='retry', name='sdk/' + scenario, observed=dict(requests=requests, frames=frames, logName=log_name, log=lines, liveBarrier=barrier))


def validate_imports(capture, root, executable, expected_modules, check_files=True):
    runtime = capture['runtime']
    root = Path(root).resolve()
    if Path(runtime['root']).resolve() != root or not runtime['python'].startswith('3.8.10 ') or Path(runtime['executable']).resolve() != Path(executable).resolve():
        raise ValueError('SDK selected native runtime differs')
    modules = runtime.get('modules')
    required = set(IMPORTS[capture['scenario']])
    allowed = required | ({OPTIONAL_CANCEL_IMPORT} if capture['scenario'] == 'cancel' else set())
    if not isinstance(modules, dict) or not required.issubset(modules) or not set(modules).issubset(allowed):
        raise ValueError('SDK actual imported closure differs')
    missing_prefixes = None if check_files else {}
    for name, expected in modules.items():
        if expected != expected_modules.get(name):
            raise ValueError('SDK imported bytes disagree with approved closure')
        path = resolve_import_path(root, name, missing_prefixes)
        if path.relative_to(root).as_posix() != name or not name.startswith(('dsh/', 'apps/')) or '\\' in name or ':' in name or '..' in Path(name).parts or not isinstance(expected, str) or len(expected) != 64 or any(value not in '0123456789abcdef' for value in expected):
            raise ValueError('SDK imported identity invalid')
        if check_files and digest(path) != expected:
            raise ValueError('SDK actual imported bytes differ')


def observations(captures, destinations, side):
    if not isinstance(captures, dict) or set(captures) != set(SCENARIOS) or not isinstance(destinations, dict) or set(destinations) != set(SCENARIOS):
        raise ValueError('SDK complete scenario set missing')
    if side not in ('source', 'native') or any(capture.get('side') != side for capture in captures.values()):
        raise ValueError('SDK actual carrier side differs')
    rows = [public(captures[scenario], scenario, Path(destinations[scenario])) for scenario in SCENARIOS]
    return rows, value_digest(rows, side=side)
