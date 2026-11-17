"""Partial-clone Market detail cache from the pinned 0.2.2 repository contract."""
import asyncio
import hashlib
import os
import re
import shutil
import stat
import tempfile
import time
from urllib.parse import urlsplit

from dsh.boot.market_git_022 import execute_git
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.cordis.text import trim_js
from dsh.host.http_request import request as request_http
from dsh.util.file_lock_022 import with_file_lock
from dsh.util.plugin_detail import DetailFailure, readme_name

NETWORK_FAILURE = re.compile(r'Could not resolve host|Failed to connect|Connection (?:refused|reset)|timed out|Network is unreachable|SSL|TLS', re.I)


class FileTooLarge(DetailFailure):
    def __init__(self, path, maximum):
        super().__init__('too-large', path+' exceeds '+str(maximum)+' bytes')


def size_of(path):
    total = 0
    for directory, _, files in os.walk(path):
        for name in files:
            target = os.path.join(directory, name)
            if not os.path.islink(target):
                total += os.stat(target).st_size
    return total


def remove(path):
    def retry(function, target, exception):
        info = os.lstat(target)
        # Git marks owned pack/index files read-only on Windows. Never alter a
        # link target or a shared hardlink's attributes to force deletion.
        if (os.name == 'nt' and isinstance(exception[1], PermissionError) and not stat.S_ISLNK(info.st_mode)
                and info.st_nlink == 1 and not info.st_mode & stat.S_IWRITE):
            os.chmod(target, info.st_mode | stat.S_IWRITE)
            function(target)
        else:
            raise exception[1]
    try:
        if os.path.islink(path) or not os.path.isdir(path):
            os.unlink(path)
        else:
            shutil.rmtree(path, onerror=retry)
    except FileNotFoundError:
        pass


def ssh_url_of(url):
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ('http', 'https') or parsed.username or parsed.password or parsed.query:
        return None
    host = parsed.hostname
    if ':' in host:
        host = '['+host+']'
    return 'ssh://git@'+host+parsed.path


class RepositoryCache:
    def __init__(self, options, clock=None, request=None, git=None):
        self.options = options
        self.clock = clock or (lambda: int(time.time()*1000))
        self.request, self.execute = request or request_http, git or execute_git
        self.locks, self.heads, self.visibility, self.checks = {}, {}, {}, {}
        self.running, self.git_starts = set(), False

    async def isPublic(self, url):
        cached = self.visibility.get(url)
        if cached is not None and cached['expiresAt'] > self.clock():
            return cached['value']
        if url not in self.checks:
            async def check():
                try:
                    return await self.check(url)
                finally:
                    self.checks.pop(url, None)
            self.checks[url] = asyncio.create_task(check())
            self.checks[url].add_done_callback(lambda task: None if task.cancelled() else task.exception())
        return await asyncio.shield(self.checks[url])

    async def check(self, url):
        endpoint, scope = url+'/info/refs?service=git-upload-pack', AbortController()
        detach = self.options['lifetime'].add_listener('abort', scope.abort)
        timer = asyncio.get_running_loop().call_later(self.options['timeoutMs']/1000, scope.abort,
                RuntimeError('The operation was aborted due to timeout'))
        try:
            try:
                # Never demand its body, follow redirects, or attach Git/user credentials.
                async with self.request(endpoint, 'GET', {}, None, scope.signal, redirect_policy='manual') as (response, _):
                    status = response['status']
            except Exception as error:
                raise DetailFailure('network', 'Could not reach '+endpoint+': '+str(error)) from error
        finally:
            timer.cancel()
            detach()
        public = 200 <= status < 300
        if not public and status not in (401, 403, 404) and not 300 <= status < 400:
            raise DetailFailure('network', endpoint+' answered HTTP '+str(status))
        self.visibility[url] = dict(value=public, expiresAt=self.clock()+self.options['ttlMs'])
        return public

    async def read(self, url, commit, path, max_bytes, signal):
        async def operation(repository, signal):
            resolved = await self.commit(repository, url, commit, signal)
            blob = (await self.files(repository, resolved, path, signal)).get(path)
            return None if blob is None else await self.blob(repository, url, blob, path, max_bytes, signal)
        return await self.locked(url, operation, signal)

    async def readme(self, url, commit, directory, max_bytes, signal):
        async def operation(repository, signal):
            resolved = await self.commit(repository, url, commit, signal)
            files = await self.files(repository, resolved, None if directory == '' else directory+'/', signal)
            prefix = '' if directory == '' else directory+'/'
            name = readme_name([path[len(prefix):] for path in files])
            if name is None:
                return None
            path = prefix+name
            return dict(path=path, bytes=await self.blob(repository, url, files[path], path, max_bytes, signal))
        return await self.locked(url, operation, signal)

    async def settled(self):
        await asyncio.gather(*list(self.running), return_exceptions=True)

    async def locked(self, url, operation, signal):
        repository = os.path.join(self.options['dir'], hashlib.sha256(url.encode('utf-8')).hexdigest()[:24])
        scope = AbortController()
        detach = signal.add_listener('abort', scope.abort)
        async def run():
            try:
                return await operation(repository, scope.signal)
            except BaseException as error:
                if not isinstance(error, FileTooLarge):
                    remove(repository)
                raise
        task = self.serialized(repository, run)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            scope.abort()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise
        finally:
            detach()

    def serialized(self, repository, operation):
        previous = self.locks.get(repository)
        async def run():
            if previous is not None:
                await asyncio.gather(asyncio.shield(previous), return_exceptions=True)
            os.makedirs(self.options['dir'], exist_ok=True)
            return await with_file_lock(repository, operation, 5*self.options['timeoutMs'], self.options['lifetime'])
        task = asyncio.create_task(run())
        self.locks[repository] = task
        self.running.add(task)
        def complete(done):
            if self.locks.get(repository) is done:
                self.locks.pop(repository, None)
            self.running.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(complete)
        return task

    async def commit(self, repository, url, commit, signal):
        if not self.git_starts:
            try:
                await self.run(self.options['dir'], ['--version'], signal, 1024)
            except Exception as error:
                raise DetailFailure('git-unavailable', str(error)) from error
            self.git_starts = True
        if not os.path.exists(repository):
            staging = tempfile.mkdtemp(prefix='.init-', dir=self.options['dir'])
            try:
                await self.run(staging, ['init', '--quiet', '--bare', '--template='], signal)
                for key, value in [('remote.origin.url', url), ('remote.origin.promisor', 'true'), ('remote.origin.partialclonefilter', 'blob:none')]:
                    await self.run(staging, ['config', key, value], signal)
                os.rename(staging, repository)
            finally:
                remove(staging)
        os.utime(repository, None)
        head = self.heads.get(url)
        known = commit if commit is not None else head['value'] if head is not None and head['expiresAt'] > self.clock() else None
        if known is not None and not (await self.git(['show-ref', '--verify', '--quiet', 'refs/dsh/'+known], repository, signal))['failed']:
            return known
        await self.fetch(repository, commit or 'HEAD', signal)
        fetched = commit if commit is not None else trim_js((await self.run(repository, ['rev-parse', 'FETCH_HEAD'], signal)).decode('utf-8', 'replace'))
        await self.run(repository, ['update-ref', 'refs/dsh/'+fetched, fetched], signal)
        if commit is None:
            self.heads[url] = dict(value=fetched, expiresAt=self.clock()+self.options['ttlMs'])
        return fetched

    async def fetch(self, repository, target, signal):
        args = ['fetch', '--quiet', '--depth', '1', '--filter=blob:none', '--no-tags', 'origin', target]
        remote = trim_js((await self.run(repository, ['config', 'remote.origin.url'], signal, 65536)).decode('utf-8', 'replace'))
        try:
            await self.watched(repository, remote, args, signal, remote+': git fetch')
        except DetailFailure as error:
            ssh = ssh_url_of(remote)
            if ssh is None or error.reason != 'denied':
                raise
            await self.run(repository, ['config', 'remote.origin.url', ssh], signal)
            try:
                await self.watched(repository, ssh, args, signal, ssh+': git fetch')
            except DetailFailure as second:
                if second.reason == 'too-large':
                    raise
                raise DetailFailure('network' if second.reason == 'network' else 'denied', str(error)+'\n'+str(second)) from second
        await self.evict(repository)

    async def watched(self, repository, url, args, signal, label, maximum=None):
        limit, before, oversized = self.options['maxRepositoryBytes'], size_of(repository), AbortController()
        async def watch():
            while True:
                await asyncio.sleep(self.options['sizePollMs']/1000)
                try:
                    if size_of(repository)-before > limit:
                        oversized.abort()
                except OSError:
                    pass
        watching = asyncio.create_task(watch())
        try:
            result = await self.git(args, repository, signal, oversized.signal, maximum)
        finally:
            watching.cancel()
            await asyncio.gather(watching, return_exceptions=True)
        if oversized.signal.aborted or not result['failed'] and size_of(repository)-before > limit:
            raise DetailFailure('too-large', url+': one fetch adds more than '+str(limit)+' bytes')
        if result['failed'] and not result['overflowed']:
            raise DetailFailure('network' if NETWORK_FAILURE.search(result['diagnostic']) else 'denied', label+': '+result['diagnostic'])
        return result

    async def evict(self, kept):
        entries, now = [], self.clock()
        for name in os.listdir(self.options['dir']):
            path = os.path.join(self.options['dir'], name)
            try:
                used = os.stat(path).st_mtime*1000
                if name.startswith('.init-'):
                    if now-used > self.options['timeoutMs']:
                        remove(path)
                elif os.path.isdir(path) and not os.path.islink(path):
                    entries.append(dict(path=path, used=used, size=size_of(path)))
            except OSError:
                pass
        total = sum(entry['size'] for entry in entries)
        for entry in sorted(entries, key=lambda entry: (entry['path'] == kept, entry['used'])):
            if total <= self.options['maxCacheBytes']:
                return
            async def delete(path=entry['path']):
                remove(path)
            self.serialized(entry['path'], delete)
            total -= entry['size']

    async def files(self, repository, commit, path, signal):
        listing = await self.run(repository, ['ls-tree', '-z', commit]+([] if path is None else ['--', path]), signal)
        files = {}
        for line in listing.decode('utf-8', 'replace').split('\0'):
            match = re.fullmatch(r'100(?:644|755) blob ([0-9a-f]+)\t(.+)', line, re.S)
            if match:
                files[match[2]] = match[1]
        return files

    async def blob(self, repository, url, blob, path, maximum, signal):
        result = await self.watched(repository, url, ['cat-file', 'blob', blob], signal, 'git cat-file '+path, maximum)
        if result['overflowed']:
            raise FileTooLarge(path, maximum)
        await self.evict(repository)
        return result['stdout']

    async def run(self, repository, args, signal, maximum=None):
        result = await self.git(args, repository, signal, maximum=maximum)
        if result['failed']:
            raise RuntimeError('git '+args[0]+': '+result['diagnostic'])
        return result['stdout']

    async def git(self, args, cwd, signal, stop=NEVER_ABORTED, maximum=None):
        return await self.execute(args, cwd, signal, self.options['lifetime'], self.options['timeoutMs'],
                self.options['maxRepositoryBytes'] if maximum is None else maximum,
                self.options['maxRepositoryBytes'], self.options['transports'], stop)
