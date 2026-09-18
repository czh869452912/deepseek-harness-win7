"""Real concurrent streams, cursor reconnects and local model configuration."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.goose'))
from console_runtime import append_event, read_events, load_config, write_config, config_revision
from project_console import make_server
from parity_runner import Stream, run_process
from project_runner import repeated_issues


def test_role_effort_isolated_between_parallel_child_processes(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv('GOOSE_THINKING_EFFORT', 'low')
    def worker(effort):
        log = tmp_path / (effort + '.log')
        assert run_process([sys.executable, '-c', "import os; print(os.environ['GOOSE_THINKING_EFFORT'])"],
                           tmp_path, log, lambda *args: None, 10, thinking_effort=effort) == 0
        return log.read_text(encoding='utf-8').strip()
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(worker, ['medium', 'high'])) == ['medium', 'high']
    assert os.environ['GOOSE_THINKING_EFFORT'] == 'low'


def test_config_effort_validation_and_legacy_compatibility():
    from console_runtime import validate_config
    config = load_config(Path(__file__).resolve().parents[1])
    assert config['roles']['reviewer']['thinking_effort'] == 'medium'
    assert config['roles']['judge']['thinking_effort'] == 'high'
    config['roles']['reviewer']['thinking_effort'] = 'invalid'
    with pytest.raises(ValueError, match='thinking_effort'):
        validate_config(config)
    config['roles']['reviewer'].pop('thinking_effort')
    validate_config(config)


def test_parallel_workers_keep_complete_tool_results_and_thinking(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOSE_PROJECT_OUTPUT', 'quiet')
    def worker(name):
        folder = tmp_path / name
        folder.mkdir()
        state = dict(unit=name, phase='migrate', round=1, attempt=name)
        stream = Stream(lambda k, v: append_event(folder, state, k, v))
        code = "import json\n"
        code += "for i in range(50):\n"
        code += " print(json.dumps({'type':'message','message':{'role':'assistant','content':[{'type':'thinking','thinking':str(i)}, {'type':'toolResponse','id':str(i),'toolResult':{'text':'LINE1\\nLINE2'}}]}}),flush=True)\n"
        code += "print(json.dumps({'type':'complete'}),flush=True)\n"
        code += "print('tail stderr',flush=True)\n"
        assert run_process([sys.executable, '-c', code], folder, folder / 'raw.jsonl',
                           lambda k, v: append_event(folder, state, k, v), 10, stream) == 0
        events, cursor = read_events(folder / 'progress.jsonl', limit=1000)
        assert sum(e['kind'] == 'thinking' for e in events) == 50
        assert sum(e['kind'] == 'tool_result' for e in events) == 50
        assert all(e['task'] == name for e in events)
        assert len({e['seq'] for e in events}) == len(events)
        assert read_events(folder / 'progress.jsonl', cursor) == ([], cursor)
        assert 'tail stderr' in (folder / 'raw.jsonl').read_text(encoding='utf-8')
        return events
    with ThreadPoolExecutor(2) as pool:
        assert all(pool.map(worker, ['alpha', 'beta']))


def test_pause_drains_backlog_and_retries_retain_raw_log(tmp_path):
    stop = threading.Event()
    count = [0]
    def notify(kind, value):
        if kind == 'tool_result':
            count[0] += 1
            stop.set()
    stream = Stream(notify)
    # A single write guarantees a backlog already in the pipe at cancellation.
    code = "import sys,json,time\ne=json.dumps({'type':'message','message':{'role':'user','content':[{'type':'toolResponse','toolResult':{'value':'done'}}]}})\nsys.stdout.write((e+'\\n')*50);sys.stdout.flush();time.sleep(30)"
    path = tmp_path / 'raw.jsonl'
    with pytest.raises(InterruptedError):
        run_process([sys.executable, '-c', code], tmp_path, path, notify, 5, stream, cancel_event=stop)
    assert len(path.read_text(encoding='utf-8').splitlines()) == 50
    assert count[0] == 50
    run_process([sys.executable, '-c', "print('next attempt')"], tmp_path, path, lambda *a: None, 5)
    archived = list(tmp_path.glob('raw.attempt-*.jsonl'))
    assert len(archived) == 1
    assert len(archived[0].read_text(encoding='utf-8').splitlines()) == 50
    assert 'next attempt' in path.read_text(encoding='utf-8')


def test_byte_cursor_waits_for_partial_utf8_line_and_reconnects(tmp_path):
    path = tmp_path / 'events.jsonl'
    first = (json.dumps({'message': '中文'}, ensure_ascii=False) + '\n').encode('utf-8')
    path.write_bytes(first + b'{"message":')
    events, cursor = read_events(path)
    assert events[0]['message'] == '中文'
    assert cursor == len(first)
    with path.open('ab') as file:
        file.write(b'"second"}\n')
    events, next_cursor = read_events(path, cursor)
    assert [e['message'] for e in events] == ['second']
    assert read_events(path, next_cursor)[0] == []


def test_heartbeat_does_not_replace_last_useful_activity(tmp_path, monkeypatch):
    monkeypatch.setenv('GOOSE_PROJECT_OUTPUT', 'quiet')
    state = dict(unit='a', phase='review', round=1)
    append_event(tmp_path, state, 'agent', 'checking lifecycle')
    append_event(tmp_path, state, 'heartbeat', 'idle')
    assert state['last_activity']['message'] == 'checking lifecycle'
    assert state['last_heartbeat']['message'] == 'idle'


def test_model_editor_atomic_update_origin_token_and_stale_revision(tmp_path):
    (tmp_path / '.goose').mkdir()
    server = make_server(tmp_path, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = 'http://127.0.0.1:%d' % server.server_port
    try:
        with urlopen(base + '/api/config') as response:
            initial = json.load(response)
        initial['config']['roles']['migrator']['model'] = 'replacement-model'
        payload = json.dumps({'config': initial['config'], 'revision': initial['revision']}).encode()
        req = Request(base + '/api/config', payload, {'Content-Type': 'application/json'}, method='POST')
        with pytest.raises(HTTPError) as rejected:
            urlopen(req)
        assert rejected.value.code == 403
        req.add_header('Origin', base)
        req.add_header('X-Console-Token', initial['token'])
        with urlopen(req) as response:
            assert json.load(response)['revision'] != initial['revision']
        assert load_config(tmp_path)['roles']['migrator']['model'] == 'replacement-model'
        with pytest.raises(HTTPError) as stale:
            urlopen(req)
        assert stale.value.code == 400
        with pytest.raises(HTTPError):
            urlopen(Request(base + '/api/config', headers={'Host': 'attacker.example'}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_config_rejects_secret_fields(tmp_path):
    value = load_config(tmp_path)
    value['roles']['judge']['api_key'] = 'do-not-store'
    with pytest.raises(ValueError, match='expected provider, model and optional thinking_effort'):
        write_config(tmp_path, value, config_revision(value))


def test_repeated_invariant_ignores_punctuation_and_unrelated_tree_changes():
    old = {'review': {'issues': [{'id': 'reference/vendor/cordis/src/fiber.ts#reload-microtask'}]}}
    assert repeated_issues({'issues': [{'id': 'reference/vendor/cordis/src/fiber.ts#_reload-initial-microtask'}]}, old)
    assert not repeated_issues({'issues': [{'id': 'reference/vendor/schema/src/number.ts#maximum'}]}, old)


def test_terminal_disconnect_does_not_drop_persisted_events(tmp_path, monkeypatch):
    def disconnected(*args, **kwargs):
        raise BrokenPipeError('terminal disconnected')
    monkeypatch.setattr('builtins.print', disconnected)
    monkeypatch.setenv('GOOSE_PROJECT_OUTPUT', 'plain')
    state = dict(unit='a', phase='migrate', round=1)
    append_event(tmp_path, state, 'tool', 'retained')
    assert read_events(tmp_path / 'progress.jsonl')[0][0]['message'] == 'retained'


def test_token_storm_is_batched_without_losing_whitespace(monkeypatch):
    import parity_runner
    clock = [100.0]
    monkeypatch.setattr(parity_runner.time, 'monotonic', lambda: clock[0])
    output = []
    stream = Stream(lambda k, v: output.append((k, v, None)),
                    lambda k, v, identity: output.append((k, v, identity)))
    fragments = ['中', ' ', '\n', 'word'] * 2500
    for fragment in fragments:
        stream.feed({'message': {'id': 'one', 'role': 'assistant',
                    'content': [{'type': 'thinking', 'thinking': fragment}]}})
    clock[0] += 0.5
    stream.flush_due()
    assert ''.join(row[1] for row in output) == ''.join(fragments)
    assert len(output) <= 4  # 10,000 deltas cause only a handful of progress writes.
    assert len(set(row[2] for row in output)) == 1
    stream.feed({'message': {'id': 'two', 'role': 'assistant',
                'content': [{'type': 'text', 'text': 'final '}]}})
    stream.feed({'type': 'complete'})
    assert output[-1][:2] == ('agent', 'final ')
    assert output[-1][2] != output[0][2]


def test_status_checkpoint_is_throttled_but_phase_end_is_immediate(tmp_path, monkeypatch):
    import parity_runner
    monkeypatch.setenv('GOOSE_PROJECT_OUTPUT', 'quiet')
    clock = [100.0]
    monkeypatch.setattr(parity_runner.time, 'monotonic', lambda: clock[0])
    saves = []
    monkeypatch.setattr(parity_runner, 'save_json', lambda *args: saves.append(args))
    runner = object.__new__(parity_runner.Runner)
    runner.run_dir = tmp_path
    runner.state = dict(unit='alpha', phase='migrate', round=1)
    for _ in range(100):
        runner.notify('thinking', 'chunk')
    assert len(saves) == 1
    clock[0] += 0.5
    runner.notify('thinking', 'next')
    assert len(saves) == 2
    runner.notify('draining', 'done')
    assert len(saves) == 3
    assert runner.state['execution_state'] == 'DRAINING'


def test_idle_stream_flushes_before_process_completion(tmp_path):
    observed = []
    stream = Stream(lambda k, v: observed.append((k, v)))
    code = ("import json,time\n"
            "print(json.dumps({'message':{'role':'assistant','id':'one','content':"
            "[{'type':'thinking','thinking':'partial '}]}}),flush=True)\n"
            "time.sleep(1)\nprint(json.dumps({'type':'complete'}),flush=True)")
    def notify(kind, value):
        if kind == 'draining':
            assert ('thinking', 'partial ') in observed
    assert run_process([sys.executable, '-c', code], tmp_path, tmp_path / 'raw.jsonl',
                       notify, 5, stream) == 0
    assert observed == [('thinking', 'partial ')]


def test_loopback_proxy_bypass_preserves_external_proxy(tmp_path, monkeypatch):
    from console_runtime import worker_environment
    import subprocess
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    monkeypatch.setenv('NO_PROXY', 'internal.example,other.example')
    env = worker_environment()
    code = "from urllib.request import proxy_bypass; assert all(proxy_bypass(h) for h in ['localhost:80', '127.0.0.1:80', '[::1]:80', 'internal.example', 'other.example']); assert not proxy_bypass('external.example')"
    subprocess.check_call([sys.executable, '-c', code], env=env)
    assert env['HTTP_PROXY'] == 'http://127.0.0.1:9'
