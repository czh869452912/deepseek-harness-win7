import asyncio
from contextlib import asynccontextmanager
import hashlib
import os
from pathlib import Path
import subprocess
import shlex
import sys
import time

import pytest

from dsh.boot.market_git_022 import execute_git, git_environment
from dsh.boot.market_repository_cache_022 import RepositoryCache, FileTooLarge, ssh_url_of
from dsh.core.abort import AbortController
from dsh.util.file_lock_022 import with_file_lock, holder_exited
from dsh.util.plugin_detail import DetailFailure
from scripts.rc022_market_git_probe import fixture, observe_fixture


def cache(root, **overrides):
    options = dict(dir=str(root/'cache'), maxRepositoryBytes=10*1024*1024, maxCacheBytes=100*1024*1024,
                   timeoutMs=10000, ttlMs=60000, transports=['file'], lifetime=AbortController().signal, sizePollMs=1)
    options.update(overrides)
    return RepositoryCache(options)


@pytest.mark.asyncio
async def test_real_git_binary_commits_readmes_and_deferred_eviction(tmp_path):
    data = fixture(tmp_path/'origin')
    rows = await observe_fixture(data, tmp_path/'cache')
    assert rows[0] == dict(value=[0, 255, 128, 10])
    assert rows[3]['error'] == dict(reason='too-large', message='big.bin exceeds 100 bytes')
    assert rows[4]['value'] == dict(path='Readme.md', bytes=list(b'# Second\n'))
    assert rows[5]['value']['bytes'] == list(b'# First\n')
    assert rows[10] == dict(clones=1, running=0)
    assert rows[-1] == dict(clones=0, running=0)


@pytest.mark.asyncio
async def test_two_caches_serialize_actual_same_repository(tmp_path):
    data = fixture(tmp_path/'origin')
    left, right = cache(tmp_path), cache(tmp_path)
    results = await asyncio.gather(*[owner.read(data['url'], data['first'], 'Readme.md', 100, owner.options['lifetime'])
                                   for owner in (left, right, left, right)])
    assert results == [b'# First\n']*4
    await asyncio.gather(left.settled(), right.settled())
    assert len(list((tmp_path/'cache').iterdir())) == 1


@pytest.mark.asyncio
async def test_concurrent_repositories_evict_without_deadlock(tmp_path):
    left, right = fixture(tmp_path/'a'), fixture(tmp_path/'b')
    owner = cache(tmp_path, maxCacheBytes=1)
    values = await asyncio.wait_for(asyncio.gather(*[owner.read(data['url'], data['first'], 'Readme.md', 100,
        owner.options['lifetime']) for data in (left, right)]), 15)
    assert values == [b'# First\n', b'# First\n']
    await owner.settled()
    assert list((tmp_path/'cache').iterdir()) == []


@pytest.mark.asyncio
async def test_cached_default_head_ttl_and_eviction_refetch(tmp_path):
    data = fixture(tmp_path/'origin'); owner = cache(tmp_path)
    now = [100]; owner.clock = lambda: now[0]; signal = owner.options['lifetime']
    assert await owner.read(data['url'], None, 'Readme.md', 100, signal) == b'# Second\n'
    subprocess.check_call(['git', '-C', str(tmp_path/'origin'), 'update-ref', 'refs/heads/main', data['first']])
    assert await owner.read(data['url'], None, 'Readme.md', 100, signal) == b'# Second\n'
    now[0] += 60000
    assert await owner.read(data['url'], None, 'Readme.md', 100, signal) == b'# First\n'
    owner.options['maxCacheBytes'] = 1
    await owner.read(data['url'], None, 'Readme.md', 100, signal); await owner.settled()
    owner.options['maxCacheBytes'] = 100*1024*1024
    assert await owner.read(data['url'], None, 'Readme.md', 100, signal) == b'# First\n'
    await owner.settled()


@pytest.mark.asyncio
async def test_eviction_lru_and_staging_age(tmp_path):
    from dsh.boot.market_repository_cache_022 import size_of
    data = [fixture(tmp_path/name) for name in ('a', 'b', 'c')]
    owner = cache(tmp_path); signal = owner.options['lifetime']; directory = tmp_path/'cache'
    paths = [directory/hashlib.sha256(item['url'].encode('utf-8')).hexdigest()[:24] for item in data]
    for item in data[:2]: await owner.read(item['url'], item['first'], 'Readme.md', 100, signal)
    one = size_of(str(paths[0])); owner.options['maxCacheBytes'] = int(one*2.5)
    os.utime(str(paths[0]), (1, 1))
    stale, current = directory/'.init-old', directory/'.init-current'
    stale.mkdir(); current.mkdir(); os.utime(str(stale), (0, 0))
    await owner.read(data[2]['url'], data[2]['first'], 'Readme.md', 100, signal); await owner.settled()
    assert not stale.exists() and current.exists()
    assert not paths[0].exists() and paths[1].exists() and paths[2].exists()


@pytest.mark.asyncio
async def test_download_growth_refuses_and_deletes_clone(tmp_path):
    data = fixture(tmp_path/'origin'); owner = cache(tmp_path, maxRepositoryBytes=1024)
    with pytest.raises(DetailFailure) as error:
        await owner.read(data['url'], data['first'], 'Readme.md', 100, owner.options['lifetime'])
    assert error.value.reason == 'too-large'
    await owner.settled()
    assert list((tmp_path/'cache').iterdir()) == []


@pytest.mark.asyncio
async def test_missing_git_fails_before_initialization(tmp_path, monkeypatch):
    monkeypatch.setenv('PATH', str(tmp_path/'empty'))
    owner = cache(tmp_path)
    with pytest.raises(DetailFailure, match='git --version') as error:
        await owner.read('https://git.example/a/b.git', None, 'x', 100, owner.options['lifetime'])
    assert error.value.reason == 'git-unavailable'
    await owner.settled()
    assert list((tmp_path/'cache').iterdir()) == []


@pytest.mark.asyncio
async def test_git_failure_deletes_clone_and_does_not_poison_retry(tmp_path):
    owner = cache(tmp_path); data = fixture(tmp_path/'origin'); signal = owner.options['lifetime']
    await owner.read(data['url'], data['first'], 'Readme.md', 100, signal)
    clone = next((tmp_path/'cache').iterdir())
    refs = clone/'refs'/'dsh'
    import shutil
    shutil.rmtree(str(refs)); refs.write_text('not a directory', encoding='utf-8')
    with pytest.raises(RuntimeError, match='git update-ref') as error:
        await owner.read(data['url'], data['second'], 'Readme.md', 100, signal)
    assert not isinstance(error.value, DetailFailure)
    assert not clone.exists()
    assert await owner.read(data['url'], data['second'], 'Readme.md', 100, signal) == b'# Second\n'
    await owner.settled()


@pytest.mark.asyncio
async def test_actual_git_timeout_owns_ssh_descendant(tmp_path, monkeypatch):
    script = tmp_path/'ssh.py'; pid = tmp_path/'pid'
    script.write_text('import os,time\nopen('+repr(str(pid))+',"w").write(str(os.getpid()))\ntime.sleep(60)\n', encoding='utf-8')
    monkeypatch.setenv('GIT_SSH_COMMAND', ' '.join(shlex.quote(value.replace('\\', '/')) for value in [sys.executable, str(script)]))
    owner = cache(tmp_path, timeoutMs=1500, transports=['ssh'])
    started = time.monotonic()
    with pytest.raises(DetailFailure) as error:
        await owner.read('ssh://git@git.example/o/r.git', None, 'README', 100, owner.options['lifetime'])
    assert error.value.reason == 'network'
    assert 'timed out' in str(error.value)
    assert time.monotonic()-started < 10
    assert pid.exists(), 'fixture must start an actual SSH descendant'
    assert holder_exited(pid.read_text(encoding='utf-8')+'\n')
    await owner.settled()
    assert list((tmp_path/'cache').iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['caller', 'lifetime', 'task'])
async def test_cancel_real_ssh_process_and_remove_clone(tmp_path, monkeypatch, mode):
    script = tmp_path/'ssh.py'; pid = tmp_path/'pid'
    script.write_text('import os,time\nopen('+repr(str(pid))+',"w").write(str(os.getpid()))\ntime.sleep(60)\n', encoding='utf-8')
    monkeypatch.setenv('GIT_SSH_COMMAND', ' '.join(shlex.quote(value.replace('\\', '/')) for value in [sys.executable, str(script)]))
    caller, lifetime = AbortController(), AbortController()
    owner = cache(tmp_path, lifetime=lifetime.signal, transports=['ssh'])
    task = asyncio.create_task(owner.read('ssh://git@git.example/o/r.git', None, 'README', 100, caller.signal))
    try:
        for _ in range(500):
            if pid.exists(): break
            if task.done(): await task
            await asyncio.sleep(0.01)
        assert pid.exists()
        reason = RuntimeError('stopped read')
        if mode == 'task': task.cancel()
        else: (caller if mode == 'caller' else lifetime).abort(reason)
        with pytest.raises(asyncio.CancelledError if mode == 'task' else RuntimeError) as error:
            await asyncio.wait_for(task, 5)
        if mode != 'task': assert error.value is reason
        await owner.settled()
        assert holder_exited(pid.read_text(encoding='utf-8')+'\n')
        assert list((tmp_path/'cache').iterdir()) == []
    finally:
        caller.abort(); lifetime.abort()
        await asyncio.gather(task, return_exceptions=True)
        await owner.settled()


@pytest.mark.asyncio
async def test_visibility_shared_ttl_no_body_and_manual_redirect(tmp_path):
    calls, now, status = [], [10], [200]
    @asynccontextmanager
    async def request(url, method, headers, body, signal, **kwargs):
        calls.append((url, method, headers, kwargs))
        await asyncio.sleep(0.01)
        yield dict(status=status[0]), None
    owner = cache(tmp_path); owner.request = request; owner.clock = lambda: now[0]
    url = 'https://git.example/o/r.git'
    assert await asyncio.gather(owner.isPublic(url), owner.isPublic(url)) == [True, True]
    assert await owner.isPublic(url)
    assert len(calls) == 1 and calls[0][0] == url+'/info/refs?service=git-upload-pack'
    assert calls[0][2] == {} and calls[0][3] == dict(redirect_policy='manual')
    status[0] = 302; now[0] += 60000
    assert not await owner.isPublic(url)
    status[0] = 500; now[0] += 60000
    with pytest.raises(DetailFailure, match='HTTP 500') as error:
        await owner.isPublic(url)
    assert error.value.reason == 'network'
    assert not owner.checks


def test_git_environment_strips_overrides_but_keeps_user_ssh(monkeypatch):
    monkeypatch.setenv('GIT_DIR', 'poison'); monkeypatch.setenv('GIT_CONFIG_GLOBAL', 'poison')
    monkeypatch.setenv('GIT_SSH_COMMAND', 'custom ssh'); monkeypatch.setenv('MY_API_TOKEN', 'secret')
    env = git_environment()
    assert 'GIT_DIR' not in env and 'GIT_CONFIG_GLOBAL' not in env and 'MY_API_TOKEN' not in env
    assert env['GIT_SSH_COMMAND'] == 'custom ssh'
    assert env['GIT_TERMINAL_PROMPT'] == '0' and env['GIT_LITERAL_PATHSPECS'] == '1'


@pytest.mark.parametrize('url,expected', [('https://host:8443/a/b.git', 'ssh://git@host/a/b.git'),
    ('http://[::1]:80/a/b.git', 'ssh://git@[::1]/a/b.git'), ('ssh://git@host/a/b.git', None),
    ('https://user@host/a/b.git', None), ('https://host/a/b.git?q=x', None)])
def test_ssh_retry_url(url, expected):
    assert ssh_url_of(url) == expected


@pytest.mark.asyncio
async def test_writer_lock_dead_pid_takeover_then_release(tmp_path):
    # This is a real, exited child, not a guessed unused PID.
    child = subprocess.Popen([sys.executable, '-c', 'pass']); child.wait()
    path = tmp_path/'record'; lock = tmp_path/'record.lock'
    lock.write_text(str(child.pid)+'\n', encoding='utf-8')
    async def run():
        assert lock.read_text(encoding='utf-8') == str(os.getpid())+'\n'
        return 7
    assert await with_file_lock(path, run) == 7
    assert not lock.exists() and not list(tmp_path.glob('*.takeover-*'))


@pytest.mark.asyncio
@pytest.mark.parametrize('record', ['', '0\n', '2147483648\n', 'bad\n'])
async def test_incomplete_or_invalid_lock_is_not_taken_over(tmp_path, record):
    path = tmp_path/'record'; lock = tmp_path/'record.lock'; lock.write_text(record, encoding='utf-8')
    async def run(): raise AssertionError('must not acquire')
    with pytest.raises(RuntimeError, match='timed out waiting'):
        await with_file_lock(path, run, wait_ms=1)
    assert lock.read_text(encoding='utf-8') == record


@pytest.mark.asyncio
async def test_waiting_lock_preserves_abort_reason(tmp_path):
    path = tmp_path/'record'; lock = tmp_path/'record.lock'; lock.write_text(str(os.getpid())+'\n', encoding='utf-8')
    control = AbortController(); reason = RuntimeError('lock stopped')
    async def run(): raise AssertionError('must not acquire')
    task = asyncio.create_task(with_file_lock(path, run, signal=control.signal))
    await asyncio.sleep(0); control.abort(reason)
    with pytest.raises(RuntimeError) as error: await task
    assert error.value is reason
    assert lock.exists()
