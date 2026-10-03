import asyncio
import json
import sys

from dsh.subprocess.service import scrubbed_parent_env
from dsh.mcp.protocol import ABSENT, McpClientProtocol, McpError, PROTOCOL_VERSIONS


class StdioMcpClient(McpClientProtocol):
    def __init__(self, command, args=None, env=None, cwd=''):
        super().__init__()
        self.command, self.args, self.env, self.cwd = command, list(args or []), dict(env or {}), cwd
        self.proc = None
        self._spawn_task = None
        self._reader = None
        self._stderr = None
        self._write_lock = asyncio.Lock()
        self.stderr = bytearray()

    def _connected(self):
        return self.proc is not None and not self._closed

    async def connect(self):
        if self._spawn_task is not None or self._closed or self._closing is not None:
            raise RuntimeError('MCP transport can only be started once')
        environment = scrubbed_parent_env()
        environment.update(self.env)
        try:
            options = {'creationflags': 0x08000000} if sys.platform == 'win32' else {}
            self._spawn_task = asyncio.create_task(asyncio.create_subprocess_exec(self.command, *self.args,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd or None, env=environment, **options))
            self.proc = await asyncio.shield(self._spawn_task)
            self._start_io()
            if self._closing is not None:
                await self.close()
                raise McpError(-32000, 'Connection closed')
            return await self._initialize()
        except OSError as error:
            await self.close()
            raise McpError(-32000, 'Connection closed') from error
        except BaseException:
            await self.close()
            raise

    def _start_io(self):
        if self._reader is None:
            self._reader = asyncio.create_task(self._read())
            self._stderr = asyncio.create_task(self._read_stderr())

    async def _write(self, packet):
        async with self._write_lock:
            if self.proc is None or self._closed or self.proc.stdin.is_closing():
                raise RuntimeError('Not connected')
            self.proc.stdin.write((json.dumps(packet, ensure_ascii=True, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8'))
            await self.proc.stdin.drain()

    async def _read_stderr(self):
        while True:
            chunk = await self.proc.stderr.read(4096)
            if not chunk:
                return
            self.stderr.extend(chunk)

    async def _read(self):
        buffered = bytearray()
        try:
            while True:
                chunk = await self.proc.stdout.read(4096)
                if not chunk:
                    return
                buffered.extend(chunk)
                while b'\n' in buffered:
                    index = buffered.index(b'\n')
                    line = bytes(buffered[:index])
                    del buffered[:index + 1]
                    try:
                        packet = json.loads(line.decode('utf-8', errors='replace'),
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON number: ' + value)))
                        await self._receive(packet)
                    except (ValueError, TypeError, KeyError) as error:
                        self._callback(self.on_error, error)
        except (OSError, RuntimeError) as error:
            self._callback(self.on_error, error)
        finally:
            await self.proc.wait()
            self._disconnect()

    async def _close(self):
        if self.proc is None and self._spawn_task is not None:
            try:
                self.proc = await asyncio.shield(self._spawn_task)
                self._start_io()
            except OSError:
                pass
        if self.proc is not None:
            self.proc.stdin.close()
            try:
                await asyncio.wait_for(self.proc.wait(), 2)
            except asyncio.TimeoutError:
                if self.proc.returncode is None:
                    self.proc.terminate()
                try:
                    await asyncio.wait_for(self.proc.wait(), 2)
                except asyncio.TimeoutError:
                    if self.proc.returncode is None:
                        self.proc.kill()
                    await asyncio.wait_for(self.proc.wait(), 1)
        self._disconnect()
        for task in (self._reader, self._stderr):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*[task for task in (self._reader, self._stderr) if task is not None], return_exceptions=True)
        await self._finish_callbacks()
