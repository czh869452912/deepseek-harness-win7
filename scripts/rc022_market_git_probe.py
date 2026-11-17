"""Actual Git partial-clone detail cache compared with pinned RepositoryCache."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

FIXTURE = None


def fixture(root):
    root = Path(root); root.mkdir(parents=True)
    def git(*args):
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.check_output(['git', '-c', 'user.name=t', '-c', 'user.email=t@example.com',
            '-c', 'commit.gpgsign=false', '-c', 'core.autocrlf=false', '-C', str(root), *args], env=env).decode('utf-8').strip()
    git('init', '--quiet', '--initial-branch=main')
    git('config', 'uploadpack.allowFilter', 'true'); git('config', 'uploadpack.allowAnySHA1InWant', 'true')
    files = {'Readme.md': b'# First\n', 'readme.markdown': b'second', 'docs/README': b'docs\n',
             'docs/a b#中.png': bytes([0, 255, 128, 10]), 'big.bin': b'x'*4096}
    for path, data in files.items():
        target = root/path; target.parent.mkdir(exist_ok=True, parents=True); target.write_bytes(data)
    git('add', '-A'); git('commit', '--quiet', '-m', 'first'); first = git('rev-parse', 'HEAD')
    (root/'Readme.md').write_bytes(b'# Second\n'); git('commit', '--quiet', '-am', 'second'); second = git('rev-parse', 'HEAD')
    return dict(url=root.as_uri(), first=first, second=second)


async def observe_fixture(data, directory):
    from dsh.boot.market_repository_cache_022 import RepositoryCache
    from dsh.core.abort import AbortController
    signal = AbortController().signal
    options = dict(dir=str(directory), maxRepositoryBytes=10*1024*1024, maxCacheBytes=100*1024*1024,
        timeoutMs=10000, ttlMs=60000, transports=['file'], lifetime=signal, sizePollMs=1)
    cache = RepositoryCache(options)
    rows = []
    operations = [('read', data['first'], 'docs/a b#中.png', 100), ('read', data['first'], 'missing', 100),
                  ('read', data['first'], 'docs', 100), ('read', data['first'], 'big.bin', 100),
                  ('readme', None, '', 100), ('readme', data['first'], '', 100),
                  ('readme', data['first'], 'docs', 100), ('readme', data['first'], 'missing', 100),
                  ('read', data['second'], 'Readme.md', 100), ('read', data['first'], 'big.bin', 4096)]
    for action, commit, path, maximum in operations:
        try:
            value = await getattr(cache, action)(data['url'], commit, path, maximum, signal)
            if isinstance(value, bytes): value = list(value)
            elif value is not None: value = dict(value, bytes=list(value['bytes']))
            rows.append(dict(value=value))
        except Exception as error:
            rows.append(dict(error=dict(reason=getattr(error, 'reason', None), message=str(error))))
    await cache.settled()
    rows.append(dict(clones=len(list(Path(directory).iterdir())), running=len(cache.running)))
    # Cache total below the clone size must evict the repository after the read.
    cache.options['maxCacheBytes'] = 1
    rows.append(dict(value=list(await cache.read(data['url'], data['first'], 'Readme.md', 100, signal))))
    await cache.settled()
    rows.append(dict(clones=len(list(Path(directory).iterdir())), running=len(cache.running)))
    return rows


async def observe():
    return await observe_fixture(FIXTURE['data'], Path(FIXTURE['root'])/'native-cache')


def prepare(output):
    global FIXTURE
    data = fixture(output/'files'/'origin')
    FIXTURE = dict(data=data, root=str(output/'files'))
    path = output/'fixture.json'; path.write_text(json.dumps(FIXTURE), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_git.mts', scope='Actual Git file transport: partial-clone pinned/default commits, binary/newline bytes, missing files/trees, file size refusal preserving clone, README order, and deferred oversized-cache eviction. OS process error prose is separately qualified as a Host adaptation.',
        prepare=prepare, extra_inputs=[ROOT/'dsh/boot/market_repository_cache_022.py', ROOT/'dsh/boot/market_git_022.py', ROOT/'dsh/util/file_lock_022.py', Path(__file__).resolve()])
