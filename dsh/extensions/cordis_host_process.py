"""Win7 process ownership and initial-evaluation deadline for dynamic Host code."""
import asyncio
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from dsh.extensions.cordis_host_bridge import Peer


class HostProcess:
    def __init__(self):
        self.closed, self.job, self.api, self.pump_task = False, None, None, None
        # Bypass the Windows venv redirector so the owned PID is the interpreter.
        executable = getattr(sys, '_base_executable', None) or sys.executable
        environment = dict(os.environ, DSH_CORDIS_HOST_PATH=json.dumps(sys.path))
        self.process = subprocess.Popen([executable, '-u', '-B', str(Path(__file__).with_name('cordis_host_worker.py'))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            env=environment,
            start_new_session=os.name != 'nt',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            if os.name == 'nt':
                from dsh.sandbox.windows_acl import WinApi, JobLimit
                self.api = WinApi()
                self.job = self.api.check(self.api.CreateJobObjectW(None, None), 'CreateJobObjectW')
                limit = JobLimit()
                limit.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE, available on Win7.
                self.api.check(self.api.SetInformationJobObject(self.job, 9, ctypes.byref(limit), ctypes.sizeof(limit)),
                               'SetInformationJobObject')
                self.api.check(self.api.AssignProcessToJobObject(self.job, int(self.process._handle)),
                               'AssignProcessToJobObject')
            self.peer = Peer(self.process.stdout, self.process.stdin, 'parent')
        except BaseException:
            self.kill()
            raise

    async def ready(self):
        limit = time.monotonic() + 15
        while not getattr(self.peer, 'ready', False):
            if time.monotonic() > limit:
                raise RuntimeError('dynamic Host worker did not become ready')
            await self.peer.pump()

    async def evaluate(self, source, harness, timeout):
        await self.ready()
        key = self.peer.request('evaluate', (source,))
        limit = time.monotonic() + 15
        while key not in self.peer.answers:
            await self.peer.pump()
            # Consume already delivered completion before testing the watchdog.
            # IPC/startup latency is not model execution time.
            while not self.peer.messages.empty():
                await self.peer.pump()
            started = getattr(self.peer, 'evaluation_started', None)
            duration = getattr(self.peer, 'evaluation_duration', None)
            expired = (duration > timeout if duration is not None else
                       started is not None and (time.monotonic() - started) * 1000 > timeout)
            if expired:
                self.kill()
                raise TimeoutError('Host evaluation exceeded vmTimeoutMs')
            if time.monotonic() > limit:
                raise RuntimeError('dynamic Host worker did not deliver its evaluation result')
        plugin = self.peer.answer(key)
        await self.peer.acall('bind-harness', harness)
        return plugin

    def start_pump(self, on_failure):
        async def pump():
            try:
                while not self.closed:
                    await self.peer.pump()
            except RuntimeError as error:
                if not self.closed:
                    asyncio.create_task(on_failure(error))
        self.pump_task = asyncio.create_task(pump())

    def kill(self):
        if self.closed:
            return
        self.closed = True
        if self.job:
            self.api.CloseHandle(self.job)
            self.job = None
        if self.process.poll() is None:
            if os.name == 'nt':
                self.process.kill()
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.process.wait(timeout=5)

    async def close(self):
        self.kill()
        if self.pump_task:
            self.pump_task.cancel()
            await asyncio.gather(self.pump_task, return_exceptions=True)
        await self.peer.shutdown()
        self.peer.reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            stream.close()
        if hasattr(self, 'on_close'):
            self.on_close()
