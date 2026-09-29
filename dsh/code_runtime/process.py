"""Win7 Python process backend for the language-portable codeRuntime seam.

LEGAL_ADAPTATION: reports python/process, not typescript/worker-thread. Uses
process CPU time and a Windows Job private-memory cap, not V8 heap/ELU. Python
implicit return is JSON null. Programs remain shell-trusted, not sandboxed.
"""
import asyncio
import ctypes
import inspect
import json
import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time

from dsh.cordis.service import Service
from dsh.cordis.schema import Schema
from dsh.code_runtime.contract import validate_bindings, snapshot_json, OutputLedger, encoded
from dsh.core.cancellation import aborted


DEFAULTS = dict(computeMs=60000, maxWallMs=600000, maxOutputBytes=67108864, maxOldGenerationSizeMb=512)


class ProcessOwner:
    def __init__(self, memory):
        self.job, self.api, self.closed = None, None, False
        self.process = subprocess.Popen([sys.executable, '-u', '-B', os.path.join(os.path.dirname(__file__), 'worker.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env={'SystemRoot': os.environ.get('SystemRoot', r'C:\Windows')} if os.name == 'nt' else {},
            start_new_session=os.name != 'nt', creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            if os.name == 'nt':
                from dsh.sandbox.windows_acl import WinApi, JobLimit, P, D
                self.api = WinApi()
                self.job = self.api.check(self.api.CreateJobObjectW(None, None), 'CreateJobObjectW')
                limit = JobLimit()
                limit.basic.flags = 0x2000 | 0x100
                limit.processMemory = int(memory)
                self.api.check(self.api.SetInformationJobObject(self.job, 9, ctypes.byref(limit), ctypes.sizeof(limit)), 'SetInformationJobObject')
                # The child is blocked on its boot record; no model code can
                # run until assignment and resource limits succeed.
                self.api.check(self.api.AssignProcessToJobObject(self.job, int(self.process._handle)), 'AssignProcessToJobObject')
                self.times = self.api.kernel.QueryInformationJobObject
                self.times.argtypes, self.times.restype = [P, ctypes.c_int, P, D, P], ctypes.c_int
        except BaseException:
            self.close()
            raise

    def cpu_ms(self):
        if os.name == 'nt':
            # Job accounting includes the venv launcher and its interpreter,
            # plus any descendants. Measuring only Popen's PID misses all
            # execution when Python's Windows venv redirector is the parent.
            values = ctypes.create_string_buffer(48)
            self.api.check(self.times(self.job, 1, values, len(values), None), 'QueryInformationJobObject')
            return sum(ctypes.c_ulonglong.from_buffer(values, offset).value for offset in (0, 8)) / 10000
        if sys.platform.startswith('linux'):
            with open('/proc/{}/stat'.format(self.process.pid), encoding='utf-8') as stream:
                raw = stream.read()
            fields = raw[raw.rfind(')') + 2:].split()
            return (int(fields[11]) + int(fields[12])) * 1000 / os.sysconf('SC_CLK_TCK')
        raise RuntimeError('process CPU metering unavailable on this platform')

    def close(self):
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


class PythonProcessRuntime(Service):
    language, isolation = 'python', 'process'
    Config = Schema.object({key: Schema.number().default(value) for key, value in DEFAULTS.items()})

    def __init__(self, ctx, config=None):
        self.config = dict(DEFAULTS, **(config or {}))
        for name, value in self.config.items():
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('code runtime config {} must be positive and finite'.format(name))
        if self.config['maxOutputBytes'] < 4 or int(self.config['maxOutputBytes']) != self.config['maxOutputBytes']:
            raise ValueError('maxOutputBytes must be an integer at least four')
        if self.config['maxWallMs'] > 2147483647:
            raise ValueError('maxWallMs exceeds timer bound')
        self.closed, self.runs = False, set()
        super().__init__(ctx, 'codeRuntime')
        ctx.effect(lambda: self.dispose)

    def apply(self, ctx=None, config=None):
        pass

    async def dispose(self):
        self.closed = True
        for task in list(self.runs):
            task.cancel()
        if self.runs:
            await asyncio.gather(*list(self.runs), return_exceptions=True)

    async def run(self, request):
        if self.closed:
            raise RuntimeError('code runtime run after disposal')
        if not isinstance(request.get('program'), str):
            raise ValueError('program must be a string')
        bindings = validate_bindings(request.get('bindings'))
        task = asyncio.create_task(self._execute(request, bindings))
        self.runs.add(task)
        try:
            return await task
        except asyncio.CancelledError:
            return OutputLedger(int(self.config['maxOutputBytes'])).result(
                error=dict(kind='abort', message='code execution aborted'))
        finally:
            self.runs.discard(task)

    async def _execute(self, request, bindings):
        ledger = OutputLedger(int(self.config['maxOutputBytes']))
        failure = lambda kind, message: ledger.result(error=dict(kind=kind, message=message))
        if aborted(request.get('signal')):
            return failure('abort', 'code execution aborted')
        owner, reader = None, None
        messages = queue.Queue(maxsize=128)
        stopped = threading.Event()
        writes = asyncio.Lock()
        calls = set()
        boot_task = None
        call_ids = set()
        active = [True]
        try:
            owner = ProcessOwner(self.config['maxOldGenerationSizeMb'] * 1024 * 1024)
            process = owner.process
            loop = asyncio.get_running_loop()

            def put(value):
                while not stopped.is_set():
                    try:
                        messages.put(value, timeout=.025)
                        return
                    except queue.Full:
                        pass

            def read():
                try:
                    while not stopped.is_set():
                        # Binding traffic is independent of outer-output caps.
                        line = process.stdout.readline()
                        if not line:
                            break
                        try:
                            put(json.loads(line.decode('utf-8')))
                        except (ValueError, UnicodeError):
                            continue
                finally:
                    put({'type': 'worker-exit'})

            reader = threading.Thread(target=read, daemon=True)
            reader.start()

            async def send(value):
                data = encoded(value) + b'\n'
                async with writes:
                    if not active[0]:
                        return
                    def write():
                        process.stdin.write(data)
                        process.stdin.flush()
                    await loop.run_in_executor(None, write)

            # Rebuild metadata only; host callables never cross the wire.
            boot_bindings = [dict({'global': name, 'functions': list(binding['functions'])},
                                 **({'errorClass': binding['errorClass']} if 'errorClass' in binding else {})) for name, binding in bindings.items()]
            baseline = None
            start = time.monotonic()
            boot_task = asyncio.create_task(send(dict(program=request['program'], bindings=boot_bindings,
                            memoryBytes=int(self.config['maxOldGenerationSizeMb'] * 1024 * 1024))))

            async def invoke(message):
                try:
                    value = bindings[message['globalName']]['functions'][message['name']](snapshot_json(message.get('args')))
                    if inspect.isawaitable(value):
                        value = await value
                    reply = dict(id=message['id'], value=snapshot_json(value))
                except BaseException as error:
                    reply = dict(id=message['id'], error=str(error))
                if active[0]:
                    try:
                        await send(reply)
                    except (OSError, ValueError):
                        pass

            while True:
                if boot_task.done():
                    boot_task.result()
                if aborted(request.get('signal')):
                    return failure('abort', 'code execution aborted')
                if (time.monotonic() - start) * 1000 > self.config['maxWallMs']:
                    return failure('timeout', 'wall-time budget exceeded')
                if baseline is not None and owner.cpu_ms() - baseline > self.config['computeMs']:
                    return failure('timeout', 'compute-time budget exceeded')
                try:
                    message = messages.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(.01)
                    continue
                if not isinstance(message, dict):
                    continue
                kind = message.get('type')
                if kind == 'ready' and baseline is None:
                    baseline = owner.cpu_ms()
                    await send(dict(type='start'))
                    continue
                if kind == 'worker-exit':
                    return failure('worker-exit', 'worker exited before completion')
                if kind == 'log' and isinstance(message.get('text'), str):
                    if not ledger.admit(message['text']):
                        return ledger.limit()
                elif kind == 'call':
                    call_id, global_name, name = message.get('id'), message.get('globalName'), message.get('name')
                    if type(call_id) is not int or call_id in call_ids or not isinstance(global_name, str) or not isinstance(name, str):
                        continue
                    if global_name not in bindings or name not in bindings[global_name]['functions']:
                        continue
                    call_ids.add(call_id)
                    task = asyncio.create_task(invoke(message))
                    calls.add(task)
                    task.add_done_callback(calls.discard)
                elif kind == 'done':
                    error = message.get('error')
                    if error is not None:
                        if not isinstance(error, dict) or error.get('kind') not in ('exception', 'invalid-output', 'output-limit') or not isinstance(error.get('message'), str):
                            continue
                        return failure(error['kind'], error['message'])
                    try:
                        return ledger.result(snapshot_json(message.get('value')), has_value='value' in message)
                    except (ValueError, OverflowError, RecursionError) as error:
                        return failure('invalid-output', str(error))
        except asyncio.CancelledError:
            return failure('abort', 'code execution aborted')
        except (OSError, ValueError, RuntimeError) as error:
            return failure('worker-exit', str(error))
        finally:
            active[0] = False
            stopped.set()
            if owner is not None:
                owner.close()
                if reader is not None:
                    reader.join(timeout=2)
                owner.process.stdin.close()
                owner.process.stdout.close()
            if boot_task is not None:
                await asyncio.gather(boot_task, return_exceptions=True)
            # Binding calls are caller-owned and must not be cancelled when
            # the model run ends. They settle without writing to the dead peer.
