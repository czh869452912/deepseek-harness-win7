import asyncio
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess

from dsh.cordis.service import Service


RESOURCE_ROOT = Path(__file__).resolve().parent / 'bin'
BINARY_SHA256 = '7bfad5d6b20510e9827f466358080f02bdd4fa8f1a4666d27ae6bece4b091740'
MANIFEST_SHA256 = '5fc871398defa594c0f94849b04a7b22949325cff18b8d54f903eed5936463b9'


class JavaScriptRuntimeError(RuntimeError):
    pass


class JavaScriptParseError(JavaScriptRuntimeError):
    pass


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            value.update(chunk)
    return value.hexdigest()


def worker_environment():
    return {name: os.environ[name] for name in ('TMP', 'TEMP') if name in os.environ}


def verify_resources():
    if digest(RESOURCE_ROOT / 'runtime.json') != MANIFEST_SHA256:
        raise JavaScriptRuntimeError('JavaScript runtime manifest bytes differ')
    manifest = json.loads((RESOURCE_ROOT / 'runtime.json').read_text(encoding='utf-8'))
    if (manifest.get('binary_sha256') != BINARY_SHA256 or manifest.get('version') != '0.17.0'
            or manifest.get('source_commit') != '6d46d07d04041b40f4f49eaa7fdebe44c314c699'):
        raise JavaScriptRuntimeError('JavaScript runtime manifest differs')
    binary = RESOURCE_ROOT / 'dsh_js_worker.exe'
    if digest(binary) != BINARY_SHA256:
        raise JavaScriptRuntimeError('JavaScript worker bytes differ')
    for name, expected in manifest['resources'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or ':' in name:
            raise JavaScriptRuntimeError('JavaScript runtime resource path differs')
        if digest(RESOURCE_ROOT / relative) != expected:
            raise JavaScriptRuntimeError('JavaScript runtime resource differs: ' + name)
    return binary


def encode(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


class JavaScriptRuntime(Service):
    def __init__(self, ctx, config=None):
        self._workers = set()
        self._spawns = {}
        self._closed = False
        super().__init__(ctx, 'jsRuntime')
        async def dispose():
            self._closed = True
            await asyncio.gather(*(self._close_spawn(record) for record in list(self._spawns.values())), return_exceptions=True)
            await asyncio.gather(*(worker.dispose() for worker in list(self._workers)), return_exceptions=True)
        ctx.effect(lambda: dispose, 'jsRuntime workers')

    def parse(self, body, name):
        if self._closed:
            raise JavaScriptRuntimeError('JavaScript runtime already disposed')
        if type(body) is not str or type(name) is not str:
            raise TypeError('JavaScript body and name must be strings')
        binary = verify_resources()
        completed = subprocess.run([str(binary)], input=encode(dict(body=body, name=name, mode='parse')),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=worker_environment(),
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            frames = [json.loads(line.decode('utf-8')) for line in completed.stdout.splitlines()]
        except (UnicodeError, ValueError) as error:
            raise JavaScriptRuntimeError('JavaScript parser returned invalid protocol data') from error
        if len(frames) == 1 and frames[0].get('type') == 'parse-error' and completed.returncode == 7:
            raise JavaScriptParseError(frames[0]['error'])
        if frames != [dict(type='parsed', ok=True)] or completed.returncode != 0:
            raise JavaScriptRuntimeError('JavaScript parser failed: ' + completed.stderr.decode('utf-8', errors='replace'))

    async def open(self, request, observer=None, grace_ms=5000):
        if self._closed:
            raise JavaScriptRuntimeError('JavaScript runtime already disposed')
        binary = verify_resources()
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(str(binary), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=worker_environment(), limit=2147483647,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
        record = dict(spawn=spawn, cleanup=None)
        self._spawns[spawn] = record
        try:
            process = await asyncio.shield(spawn)
            if self._closed:
                raise JavaScriptRuntimeError('JavaScript runtime disposed during worker creation')
        except BaseException:
            await asyncio.shield(self._close_spawn(record))
            raise
        worker = JavaScriptWorker(process, observer, grace_ms)
        self._workers.add(worker)
        self._spawns.pop(spawn, None)
        worker.closed.add_done_callback(lambda _: self._workers.discard(worker))
        try:
            await worker.send(request)
            await asyncio.shield(worker.ready)
            return worker
        except BaseException:
            await worker.terminate()
            raise

    def _close_spawn(self, record):
        if record['cleanup'] is None:
            async def cleanup():
                process = await asyncio.shield(record['spawn'])
                if process.returncode is None:
                    process.kill()
                await process.communicate()
            task = asyncio.create_task(cleanup())
            record['cleanup'] = task
            task.add_done_callback(lambda _: self._spawns.pop(record['spawn'], None))
        return record['cleanup']


class JavaScriptWorker:
    def __init__(self, process, observer, grace_ms):
        self.process, self.observer, self.grace_ms = process, observer, grace_ms
        loop = asyncio.get_event_loop()
        self.ready, self.result, self.closed = loop.create_future(), loop.create_future(), loop.create_future()
        self._cancel_reason, self._disposal = None, None
        self.failure = None
        self._writer = asyncio.Lock()
        self._stderr = asyncio.create_task(process.stderr.read())
        self._reader = asyncio.create_task(self._read())
        for future in (self.ready, self.result):
            future.add_done_callback(lambda settled: None if settled.cancelled() else settled.exception())

    async def send(self, message):
        async with self._writer:
            if self.process.returncode is not None:
                raise JavaScriptRuntimeError('JavaScript worker already exited')
            self.process.stdin.write(encode(message))
            await self.process.stdin.drain()

    async def _read(self):
        terminal = False
        failure = None
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                message = json.loads(line.decode('utf-8'))
                if type(message) is not dict or type(message.get('type')) is not str:
                    raise JavaScriptRuntimeError('JavaScript worker returned invalid protocol data')
                kind = message['type']
                if kind == 'ready':
                    if self.ready.done():
                        raise JavaScriptRuntimeError('JavaScript worker repeated its startup handshake')
                    self.ready.set_result(None)
                elif kind == 'terminal':
                    if terminal or not self.ready.done():
                        raise JavaScriptRuntimeError('JavaScript worker returned an invalid terminal sequence')
                    terminal = True
                    self.result.set_result(message['result'])
                elif kind.endswith('-error'):
                    raise JavaScriptRuntimeError(message.get('error', kind))
                elif terminal or not self.ready.done() or self.observer is None:
                    raise JavaScriptRuntimeError('JavaScript worker returned an unexpected message: ' + kind)
                else:
                    observed = self.observer(message)
                    if inspect.isawaitable(observed):
                        await observed
            await self.process.wait()
            if not terminal:
                raise JavaScriptRuntimeError('JavaScript worker exited without a terminal result')
            if self.process.returncode != 0:
                raise JavaScriptRuntimeError('JavaScript worker exited with code ' + str(self.process.returncode))
        except BaseException as error:
            failure = error
            self.failure = error
            if self.process.returncode is None:
                self.process.kill()
            await self.process.wait()
        finally:
            await self._stderr
            if failure is not None:
                for future in (self.ready, self.result):
                    if not future.done():
                        future.set_exception(failure)
            if not self.closed.done():
                self.closed.set_result(None)

    async def cancel(self, reason):
        if self._cancel_reason is None and not self.result.done():
            self._cancel_reason = reason
            await self.send(dict(type='cancel', reason=reason))

    async def terminate(self):
        if self.process.returncode is None:
            self.process.kill()
        await asyncio.shield(self.closed)

    def dispose(self):
        if self._disposal is None:
            async def dispose():
                if not self.result.done():
                    try:
                        await self.cancel('workflow disposed')
                    except (BrokenPipeError, ConnectionResetError, JavaScriptRuntimeError):
                        pass
                try:
                    await asyncio.wait_for(asyncio.shield(self.closed), self.grace_ms / 1000)
                except asyncio.TimeoutError:
                    await self.terminate()
            self._disposal = asyncio.create_task(dispose())
        return self._disposal
