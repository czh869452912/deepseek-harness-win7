"""Small configuration and event primitives for the local Goose controller."""
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

OUTPUT_LOCK = threading.RLock()
CONFIG_LOCK = threading.Lock()
ROLES = ('architect', 'migrator', 'reviewer', 'judge')


def validate_config(value):
    if not isinstance(value, dict) or set(value) != {'version', 'roles'} or value['version'] != 1:
        raise ValueError('Expected version: 1 and roles; credentials are not accepted here')
    if not isinstance(value['roles'], dict) or set(value['roles']) != set(ROLES):
        raise ValueError('Configure architect, migrator, reviewer and judge')
    for role, config in value['roles'].items():
        if (not isinstance(config, dict) or not {'provider', 'model'} <= set(config) or
                set(config) - {'provider', 'model', 'thinking_effort'}):
            raise ValueError(role + ': expected provider, model and optional thinking_effort')
        if 'thinking_effort' in config and config['thinking_effort'] not in ('low', 'medium', 'high'):
            raise ValueError(role + ': thinking_effort must be low, medium or high')
        for text in config.values():
            if not isinstance(text, str) or not text.strip() or len(text) > 200 or any(ord(c) < 32 for c in text):
                raise ValueError('Invalid provider/model name')
    return value


def config_revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode('utf-8')).hexdigest()[:16]


def load_config(root):
    path = Path(root) / '.goose/agent-config.json'
    if not path.exists():
        # Compatibility for older checkouts and isolated controller fixtures.
        path = Path(__file__).with_name('agent-config.json')
    return validate_config(json.loads(path.read_text(encoding='utf-8')))


def write_config(root, value, expected_revision):
    value = validate_config(value)
    with CONFIG_LOCK:
        if config_revision(load_config(root)) != expected_revision:
            raise ValueError('Configuration changed; reload before saving')
        path = Path(root) / '.goose/agent-config.json'
        temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            os.replace(str(temp), str(path))
        finally:
            if temp.exists():
                temp.unlink()
    return config_revision(value)


def worker_environment(thinking_effort=None):
    env = os.environ.copy()
    env['DSH_TEST_PYTHON'] = sys.executable
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env.get('PATH', '')
    env['PYTHONIOENCODING'] = 'utf-8'
    # Local mock servers must not travel through an inherited HTTP proxy.
    bypass = []
    for value in (env.get('NO_PROXY', ''), env.get('no_proxy', ''),
                  'localhost,127.0.0.1,::1,[::1]'):
        for host in value.split(','):
            if host.strip() and host.strip() not in bypass:
                bypass.append(host.strip())
    env['NO_PROXY'] = env['no_proxy'] = ','.join(bypass)
    if thinking_effort is not None:
        env['GOOSE_THINKING_EFFORT'] = thinking_effort
    return env


def terminal_event(record):
    mode = os.environ.get('GOOSE_PROJECT_OUTPUT', 'summary')
    if mode == 'quiet' or record['kind'] == 'heartbeat':
        return
    if mode == 'summary' and record['kind'] in ('thinking', 'tool_result', 'check'):
        return
    prefix = '[{time}] [{task} {phase}:{round}] {kind}: '.format(**record)
    lines = str(record['message']).splitlines() or ['']
    with OUTPUT_LOCK:
        try:
            for line in lines:
                print(prefix + (line[:220] if mode == 'summary' else line), flush=True)
        except (BrokenPipeError, OSError):
            pass  # A disconnected terminal must not stop collection or execution.


def append_event(run_dir, state, kind, message, stream_id=None):
    """One writer per run. Append before rendering; byte cursors survive restart."""
    record = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'timestamp': time.time(),
              'task': state.get('unit', 'unknown'), 'run': run_dir.name,
              'attempt': state.get('attempt'), 'phase': state['phase'], 'round': state['round'],
              'kind': kind, 'message': message}
    if stream_id is not None:
        record['stream_id'] = stream_id
    with (run_dir / 'progress.jsonl').open('ab') as file:
        record['seq'] = file.tell()  # Durable monotonically increasing byte offset, not a row count.
        file.write((json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8'))
        file.flush()
    state['last_heartbeat' if kind == 'heartbeat' else 'last_activity'] = record
    terminal_event(record)
    return record


def read_events(path, offset=0, limit=200):
    """Read complete UTF-8 JSONL records only; partial writes keep their cursor."""
    result = []
    if not path.exists():
        return result, 0
    with path.open('rb') as file:
        size = file.seek(0, 2)
        if offset == -1:
            # Start at recent complete events without scanning multi-hour logs.
            file.seek(max(0, size - 128 * 1024))
            if file.tell():
                file.readline()
            offset = file.tell()
        if offset < 0 or offset > size:
            raise ValueError('Invalid event cursor')
        file.seek(offset)
        for _ in range(limit):
            start = file.tell()
            line = file.readline()
            if not line or not line.endswith(b'\n'):
                file.seek(start)
                break
            try:
                event = json.loads(line.decode('utf-8'))
            except (ValueError, UnicodeError):
                event = {'kind': 'unparsed', 'message': line.decode('utf-8', errors='replace')}
            event['cursor'] = start
            result.append(event)
        return result, file.tell()
