"""Win7 Python process backend for the language-portable codeRuntime seam.

LEGAL_ADAPTATION: reports python/process, not typescript/worker-thread. Uses
process CPU time and a Windows Job private-memory cap, not V8 heap/ELU. Python
implicit return is JSON null. Programs remain shell-trusted, not sandboxed.
"""
import asyncio
import ctypes
import codecs
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
from dsh.code_runtime.protocol import (JsonLines, QueuedBytes, PendingCalls,
                                       IncomingBytes, ProtocolError, ControlClosedError)
from dsh.core.cancellation import aborted


DEFAULTS = dict(computeMs=60000, maxWallMs=600000, maxOutputBytes=67108864, maxOldGenerationSizeMb=512)


class ProcessOwner:
    def __init__(self, memory, cwd=None, private_control=False, argv=None, windows_breakaway=False):
        self.job, self.api, self.closed = None, None, False
        self.process = None
        self.control = None
        try:
            if private_control:
                from dsh.code_runtime.control import ControlListener
                self.control = ControlListener()
            executable = getattr(sys, '_base_executable', sys.executable) if private_control else sys.executable
            self.process = subprocess.Popen(argv or [executable, '-u', '-B', os.path.join(os.path.dirname(__file__), 'worker.py')],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE if private_control else subprocess.DEVNULL,
                env={'SystemRoot': os.environ.get('SystemRoot', r'C:\Windows')} if os.name == 'nt' else {},
                cwd=cwd, start_new_session=os.name != 'nt', creationflags=0x08000000 if os.name == 'nt' else 0)
            if os.name == 'nt':
                from dsh.sandbox.windows_acl import WinApi, JobLimit, P, D
                self.api = WinApi()
                self.job = self.api.check(self.api.CreateJobObjectW(None, None), 'CreateJobObjectW')
                limit = JobLimit()
                limit.basic.flags = 0x2000 | 0x100
                if windows_breakaway:
                    limit.basic.flags |= 0x800
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
        if self.job:
            self.api.CloseHandle(self.job)
            self.job = None
        if self.process is None:
            if self.control is not None:
                self.control.close()
            self.closed = True
            return
        if self.process.poll() is None:
            if os.name == 'nt':
                self.process.kill()
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.process.wait(timeout=5)
        if self.control is not None:
            self.control.close()
        self.closed = True


class PythonProcessRuntime(Service):
    language, isolation = 'python', 'process'
    service_name = 'codeRuntime'
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
        super().__init__(ctx, self.service_name)
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
        launch = {}
        return self._cleanup_result(await self._execute_process(request, bindings, launch), launch)

    def _cleanup_result(self, result, launch):
        if launch.get('cleanupFailure') is None:
            return result
        ledger = OutputLedger(int(self.config['maxOutputBytes']))
        for text in result.get('logs', []):
            if not ledger.admit(text):
                return ledger.limit()
        return ledger.result(error=dict(kind='worker-exit',
            message='managed process cleanup failed: '+launch['cleanupFailure']))

    async def _execute_process(self, request, bindings, launch=None):
        launch = {} if launch is None else launch
        limits = self._run_limits(request)
        protocol = self._protocol_limits()
        outgoing = QueuedBytes(protocol['maxMessageBytes']) if protocol else None
        pending = PendingCalls(protocol['maxPendingCalls'], protocol['maxMessageBytes']) if protocol else None
        incoming = IncomingBytes(protocol['maxMessageBytes']) if protocol else None
        ledger = OutputLedger(int(limits['maxOutputBytes']))
        failure = lambda kind, message: ledger.result(error=dict(kind=kind, message=message))
        if aborted(request.get('signal')):
            return failure('abort', 'code execution aborted')
        owner, reader = None, None
        output_readers = []
        outputs_done = [0]
        stderr_tail = bytearray()
        messages = queue.Queue(maxsize=128)
        stopped = threading.Event()
        writes = asyncio.Lock()
        calls = set()
        boot_task = None
        call_ids = set()
        last_call_id = 0
        active = [True]
        wire_failure = [None]
        def close_owner():
            try:
                owner.close()
            except Exception as error:
                if not protocol:
                    raise
                launch['cleanupFailure'] = str(error)
        try:
            owner = ProcessOwner(limits['maxOldGenerationSizeMb'] * 1024 * 1024,
                                 self._process_cwd(request), private_control=bool(protocol),
                                 argv=launch.get('argv'), windows_breakaway=launch.get('windowsJobBreakaway', False))
            process = owner.process
            loop = asyncio.get_running_loop()

            def put(value, size=0):
                if incoming is not None and not incoming.admit(size, stopped):
                    return
                while not stopped.is_set():
                    try:
                        messages.put((value, size), timeout=.025)
                        return
                    except queue.Full:
                        pass
                if incoming is not None:
                    incoming.release(size)

            def read():
                try:
                    if protocol:
                        decoder = JsonLines(protocol['maxMessageBytes'])
                        endpoint = owner.control.accept(stopped, lambda: process.poll() is not None)
                        if endpoint is None:
                            return
                        while not stopped.is_set():
                            chunk = endpoint.read(4096)
                            if not chunk:
                                decoder.end()
                            decoder.feed(chunk, put)
                        return
                    while not stopped.is_set():
                        # Binding traffic is independent of outer-output caps.
                        line = process.stdout.readline()
                        if not line:
                            break
                        try:
                            put(json.loads(line.decode('utf-8')))
                        except (ValueError, UnicodeError):
                            continue
                except ProtocolError as error:
                    put(dict(type='protocol-error', message=str(error)))
                except (ControlClosedError, OSError, ValueError):
                    pass
                finally:
                    put({'type': 'worker-exit'})

            reader = threading.Thread(target=read, daemon=True)
            reader.start()

            if protocol:
                def read_output(stream, name):
                    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
                    try:
                        while not stopped.is_set():
                            chunk = stream.read1(min(4096, int(protocol['maxMessageBytes'])))
                            if not chunk:
                                break
                            if name == 'stderr':
                                stderr_tail.extend(chunk)
                                if len(stderr_tail) > int(limits['maxOutputBytes']):
                                    del stderr_tail[:-int(limits['maxOutputBytes'])]
                            text = decoder.decode(chunk)
                            if text:
                                put(dict(type='raw-output', text=text, stream=name), len(chunk))
                        tail = decoder.decode(b'', final=True)
                        if tail:
                            put(dict(type='raw-output', text=tail, stream=name))
                    except (OSError, ValueError):
                        pass
                    finally:
                        outputs_done[0] += 1
                for stream, name in ((process.stdout, 'stdout'), (process.stderr, 'stderr')):
                    thread = threading.Thread(target=read_output, args=(stream, name), daemon=True)
                    output_readers.append(thread)
                    thread.start()

            async def send(value, boot=False):
                if not active[0]:
                    return
                data = outgoing.admit(value) if outgoing is not None else encoded(value) + b'\n'
                try:
                    async with writes:
                        if not active[0]:
                            return
                        def write():
                            stream = process.stdin if boot or not protocol else owner.control.outgoing
                            stream.write(data)
                            stream.flush()
                        await loop.run_in_executor(None, write)
                finally:
                    if outgoing is not None:
                        outgoing.release(data)

            # Rebuild metadata only; host callables never cross the wire.
            boot_bindings = [dict({'global': name, 'functions': list(binding['functions'])},
                                 **({'errorClass': binding['errorClass']} if 'errorClass' in binding else {})) for name, binding in bindings.items()]
            baseline = None
            start = time.monotonic()
            boot = dict(program=request['program'], bindings=boot_bindings,
                        memoryBytes=int(limits['maxOldGenerationSizeMb'] * 1024 * 1024))
            if protocol:
                boot['control'] = owner.control.spec
            boot_task = asyncio.create_task(send(boot, boot=True))

            async def invoke(message, charged=0):
                try:
                    try:
                        value = bindings[message['globalName']]['functions'][message['name']](snapshot_json(message.get('args')))
                        if inspect.isawaitable(value):
                            value = await value
                        reply = dict(id=message['id'], value=snapshot_json(value))
                    except BaseException as error:
                        reply = dict(id=message['id'], error=str(error))
                finally:
                    if pending is not None:
                        pending.release(charged)
                if active[0]:
                    try:
                        await send(reply)
                    except ProtocolError as error:
                        wire_failure[0] = str(error)
                    except (OSError, ValueError):
                        pass

            while True:
                if wire_failure[0] is not None:
                    return failure('protocol', wire_failure[0])
                if boot_task.done():
                    boot_task.result()
                if aborted(request.get('signal')):
                    return failure('abort', 'code execution aborted')
                if limits['maxWallMs'] is not None and (time.monotonic() - start) * 1000 > limits['maxWallMs']:
                    return failure('timeout', 'wall-time budget exceeded')
                if baseline is not None and limits['computeMs'] is not None and owner.cpu_ms() - baseline > limits['computeMs']:
                    return failure('timeout', 'compute-time budget exceeded')
                try:
                    message, size = messages.get_nowait()
                    if incoming is not None:
                        incoming.release(size)
                except queue.Empty:
                    await asyncio.sleep(.01)
                    continue
                if not isinstance(message, dict):
                    continue
                kind = message.get('type')
                if kind == 'protocol-error' and protocol:
                    return failure('protocol', message['message'])
                if kind == 'ready' and baseline is None:
                    baseline = owner.cpu_ms() if limits['computeMs'] is not None else 0
                    await send(dict(type='start'))
                    continue
                if kind == 'worker-exit':
                    return failure('worker-exit', 'worker exited before completion')
                if kind == 'raw-output' and protocol:
                    if not ledger.admit(message['text']):
                        return ledger.limit()
                    continue
                if protocol and baseline is None:
                    return failure('protocol', 'program message arrived before readiness')
                if kind == 'log' and isinstance(message.get('text'), str):
                    if not ledger.admit(message['text']):
                        return ledger.limit()
                elif kind == 'call':
                    call_id, global_name, name = message.get('id'), message.get('globalName'), message.get('name')
                    if type(call_id) is not int or call_id in call_ids or not isinstance(global_name, str) or not isinstance(name, str):
                        if protocol:
                            return failure('protocol', 'invalid binding call')
                        continue
                    if global_name not in bindings or name not in bindings[global_name]['functions']:
                        if protocol:
                            return failure('protocol', 'program requested an undeclared binding')
                        continue
                    charged = 0
                    if pending is not None:
                        if call_id <= last_call_id:
                            return failure('protocol', 'invalid binding call identity')
                        last_call_id = call_id
                        try:
                            args = snapshot_json(message.get('args'))
                        except (ValueError, OverflowError, RecursionError):
                            return failure('protocol', 'binding arguments must be lossless JSON')
                        charged = pending.admit(args)
                    else:
                        call_ids.add(call_id)
                    task = asyncio.create_task(invoke(message, charged))
                    calls.add(task)
                    task.add_done_callback(calls.discard)
                elif kind == 'done':
                    if protocol:
                        # Completion on control can precede final inherited output.
                        # Reap the process, then drain the separately owned readers.
                        active[0] = False
                        close_owner()
                        drain_start = time.monotonic()
                        while outputs_done[0] != 2 and time.monotonic()-drain_start < 3:
                            if aborted(request.get('signal')):
                                return failure('abort', 'code execution aborted')
                            if limits['maxWallMs'] is not None and (time.monotonic()-start)*1000 > limits['maxWallMs']:
                                return failure('timeout', 'wall-time budget exceeded')
                            try:
                                extra, size = messages.get_nowait()
                                incoming.release(size)
                                if extra.get('type') == 'raw-output' and not ledger.admit(extra['text']):
                                    return ledger.limit()
                            except queue.Empty:
                                await asyncio.sleep(.01)
                        while not messages.empty():
                            extra, size = messages.get_nowait()
                            incoming.release(size)
                            if extra.get('type') == 'raw-output' and not ledger.admit(extra['text']):
                                return ledger.limit()
                    error = message.get('error')
                    if protocol and 'error' in message and error is None:
                        return failure('protocol', 'invalid program error')
                    if error is not None:
                        if not isinstance(error, dict) or error.get('kind') not in ('exception', 'invalid-output', 'output-limit') or not isinstance(error.get('message'), str):
                            if protocol:
                                return failure('protocol', 'invalid program error')
                            continue
                        return failure(error['kind'], error['message'])
                    try:
                        return ledger.result(snapshot_json(message.get('value')), has_value='value' in message)
                    except (ValueError, OverflowError, RecursionError) as error:
                        return failure('invalid-output', str(error))
                elif protocol:
                    return failure('protocol', 'invalid program message')
        except asyncio.CancelledError:
            return failure('abort', 'code execution aborted')
        except ProtocolError as error:
            return failure('protocol', str(error))
        except (OSError, ValueError, RuntimeError) as error:
            if owner is None and isinstance(error, OSError):
                launch['spawnError'] = error
            return failure('worker-exit', str(error))
        finally:
            active[0] = False
            stopped.set()
            if owner is not None:
                close_owner()
                if reader is not None:
                    reader.join(timeout=2)
                for thread in output_readers:
                    thread.join(timeout=2)
                owner.process.stdin.close()
                owner.process.stdout.close()
                if owner.process.stderr is not None:
                    owner.process.stderr.close()
                launch['exitCode'] = owner.process.returncode
            launch['stderr'] = stderr_tail.decode('utf-8', errors='replace')
            if boot_task is not None:
                await asyncio.gather(boot_task, return_exceptions=True)
            # Binding calls are caller-owned and must not be cancelled when
            # the model run ends. They settle without writing to the dead peer.

    def _run_limits(self, request):
        return self.config

    def _process_cwd(self, request):
        return None

    def _protocol_limits(self):
        return None
