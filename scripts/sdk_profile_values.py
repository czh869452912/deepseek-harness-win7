import copy
import hashlib
import json
from pathlib import Path

from scripts.canonical_llm_values import observation_digest as value_digest
from dsh.session.seq_ranges import encode_seq_ranges
from scripts.sdk_profile_cases import SCENARIOS
from scripts.import_paths import resolve_import_path


FRAME_COUNTS = dict(normal=30, cancel=14, error=18)
REPLY_POSITIONS = dict(normal=[0, 5, 29], cancel=[0, 5, 13], error=[0, 5, 17])
IMPORTS = json.loads(Path(__file__).with_name('sdk_profile_imports.json').read_text(encoding='utf-8'))
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
    count = dict(normal=25, cancel=10, error=13)[scenario]
    if [event['seq'] for event in events] != list(range(count)) or statuses != (['running'] if scenario == 'cancel' else ['running', 'idle']):
        raise ValueError('SDK event sequence or lifecycle differs')
    if len(capture['logs']) != 1:
        raise ValueError('One SDK-owned durable session required')
    log_name, payload = next(iter(capture['logs'].items()))
    lines = [json.loads(line) for line in payload.splitlines()]
    expected_events = copy.deepcopy(events)
    for event in expected_events:
        if 'sourceEventSeqs' in event:
            event['sourceEventSeqs'] = encode_seq_ranges(event['sourceEventSeqs'])
    if scenario == 'cancel':
        if len(lines) != 14 or lines[1:11] != expected_events or [event['seq'] for event in lines[1:]] != list(range(13)):
            raise ValueError('Complete cancelled durable facts differ')
        partial = lines[11]
        if partial['type'] != 'assistant/message' or partial['data'].get('interrupted') is not True:
            raise ValueError('Cancelled partial-message marker differs')
        message = partial['data']['message']
        if message['source'] != dict(kind='model', provider='deepseek-official', model='deepseek-v4-pro') or message['content'] != [dict(type='text', text='SDK_PENDING')] or partial['sourceEventSeqs'] != [8, 9]:
            raise ValueError('Cancelled partial-message route/content/causality differs')
        if lines[-2]['type'] != 'step/end' or lines[-1]['type'] != 'turn/end' or lines[-1]['data']['reason'] != dict(kind='aborted', reason=dict(kind='disposed')):
            raise ValueError('Cancellation terminal facts differ')
    else:
        if len(lines) != count + 1 or lines[1:] != expected_events:
            raise ValueError('Complete durable facts differ from emitted facts')
        if scenario == 'error':
            if any(event['type'] == 'assistant/message' for event in events):
                raise ValueError('Ordinary stream error incorrectly persists an interrupted assistant')
            if events[-1]['type'] != 'turn/end' or events[-1]['data']['reason'] != dict(kind='error', error=dict(message='SSE stream ended without [DONE]', code='STREAM_CLOSED')):
                raise ValueError('Full typed stream failure differs')
    header = lines[0]
    if set(header) != {'type', 'version', 'id', 'createdAt', 'cwd', 'delegationDepth'} or header['id'] != 'minimal-controlled' or header['cwd'] != str(destination):
        raise ValueError('SDK durable header identity differs')
    start, end = capture['startedAt'], capture['endedAt']
    times = [event['time'] for event in lines[1:]]
    if type(start) is not int or type(end) is not int or not 0 <= end - start <= 90000 or times != sorted(times) or any(type(value) is not int or not start <= value <= end for value in times):
        raise ValueError('Actual SDK clock window/order differs')
    if type(header['createdAt']) is not int or not start <= header['createdAt'] <= times[0]:
        raise ValueError('Actual SDK creation clock differs')
    for event in events + lines[1:]:
        event['time'] = ['validated-live-clock', event['seq']]
    header['createdAt'] = ['validated-live-clock', 'creation']
    return dict(group='retry', name='sdk/' + scenario, observed=dict(requests=capture['requests'], frames=frames, logName=log_name, log=lines))


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
