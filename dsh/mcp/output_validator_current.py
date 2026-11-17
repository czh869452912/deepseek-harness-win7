"""Owned persistent carrier for the pinned SDK's default schema provider."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dsh.core.cleanup import CleanupPromise
from dsh.javascript.runtime import JavaScriptRuntimeError, encode, verify_resources, worker_environment

RESOURCE_ROOT = Path(__file__).with_name('validator')
MANIFEST_SHA256 = '88f0f70ca832534e5c1a95a54c2e03303d67146dce86aef950741045f74d7f84'


def bootstrap():
    path = RESOURCE_ROOT / 'manifest.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise JavaScriptRuntimeError('MCP validator manifest bytes differ')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('format') != 'dsh-mcp-validator@1' or manifest.get('target_upstream') != '38a6a5c965aa99ab525161efb7cc5cf1fe62fced':
        raise JavaScriptRuntimeError('MCP validator Source pin differs')
    for name, expected in manifest['resources'].items():
        if Path(name).name != name or ':' in name or hashlib.sha256((RESOURCE_ROOT/name).read_bytes()).hexdigest() != expected:
            raise JavaScriptRuntimeError('MCP validator resource bytes differ')
    return '\n'.join((RESOURCE_ROOT/name).read_text(encoding='utf-8') for name in ('validator.js','driver.js'))


def consume(task):
    if not task.cancelled():
        task.exception()


class CurrentOutputValidator:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()
        self.jobs = set()
        self.closing = None
        self.sequence = 0

    async def _read(self):
        line = await asyncio.wait_for(self.process.stdout.readline(), 15)
        try:
            return json.loads(line.decode('utf-8'))
        except (ValueError, UnicodeError):
            raise JavaScriptRuntimeError('MCP validator returned invalid protocol data')

    async def _exchange(self, operation):
        async with self.lock:
            try:
                if self.process is None:
                    # This task owns spawn to exit even if its caller departs.
                    self.process = await asyncio.create_subprocess_exec(str(verify_resources()),
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        limit=2147483647, env=worker_environment(),
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    self.process.stdin.write(encode(dict(body='return null',name='mcp-validator',timeoutMs=10000,bootstrap=bootstrap())))
                    await self.process.stdin.drain()
                    ready = await self._read()
                    if ready != dict(type='ready'):
                        raise JavaScriptRuntimeError('MCP validator handshake differs: '+str(ready.get('error',''))[-800:])
                    self.process.stdin.write(encode(dict(type='go')))
                self.sequence += 1
                self.process.stdin.write(encode(dict(type='validate',id=self.sequence,operation=operation)))
                await self.process.stdin.drain()
                result = await self._read()
                if result.get('type') != 'validation-result' or result.get('id') != self.sequence or type(result.get('result')) is not dict:
                    raise JavaScriptRuntimeError('MCP validator returned unexpected result')
                return result['result']
            except BaseException:
                await self._reap()
                raise

    async def observe(self, operation):
        if self.closing is not None:
            raise JavaScriptRuntimeError('MCP validator is closed')
        task = asyncio.create_task(self._exchange(operation))
        self.jobs.add(task)
        task.add_done_callback(self.jobs.discard)
        task.add_done_callback(consume)
        return await asyncio.shield(task)

    async def _reap(self):
        if self.process is not None:
            if self.process.returncode is None:
                self.process.kill()
            await self.process.communicate()

    def close(self):
        if self.closing is None:
            async def close():
                await asyncio.gather(*list(self.jobs), return_exceptions=True)
                try:
                    if self.process is not None and self.process.returncode is None:
                        self.process.stdin.write(encode(dict(type='stop')))
                        await self.process.stdin.drain()
                        if await self._read() != dict(type='terminal',result=None):
                            raise JavaScriptRuntimeError('MCP validator close differs')
                        try:
                            await asyncio.wait_for(self.process.communicate(), 1)
                        except asyncio.TimeoutError:
                            pass
                finally:
                    await self._reap()
            self.closing = CleanupPromise(close())
        return self.closing
