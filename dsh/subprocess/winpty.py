"""WinPTY console substrate using its C ABI, with a pre-spawn owned Job.

Uses the DLL shipped by pinned pywinpty 0.5.7, not its socket/thread wrappers.
No ConPTY or post-Win7 APIs are required. Console input-wait inspection remains
unavailable: callers must identify silence as inferred_idle, never stdin_read.
"""
import asyncio
import ctypes as c
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

from dsh.sandbox.windows_acl import WinApi, JobLimit, P, D
from dsh.subprocess.types import SubprocessOutcome


def native_directory():
    if c.sizeof(c.c_void_p) == 4:
        directory = Path(__file__).parent / 'bin/winpty/x86'
        raw = (directory / 'winpty-input.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != '342e652c3f8e145ce7dd4370c5889ba981a4b2e7e7c6bae73f1d59f0deb0660d':
            raise RuntimeError('Pinned WinPTY x86 manifest differs')
        for name, identity in json.loads(raw.decode('utf-8'))['files'].items():
            if Path(name).name != name or '/' in name or '\\' in name:
                raise RuntimeError('Invalid WinPTY resource path')
            data = (directory / name).read_bytes()
            if len(data) != identity['bytes'] or hashlib.sha256(data).hexdigest() != identity['sha256']:
                raise RuntimeError('Pinned WinPTY x86 resource differs: ' + name)
        return str(directory)
    package = importlib.util.find_spec('winpty')
    if package is None:
        raise RuntimeError('Win7 terminal requires pinned pywinpty 0.5.7')
    return os.path.dirname(package.origin)


class WinPtyTerminalHandle:
    def __init__(self, spec, environment):
        directory = native_directory()
        # LOAD_WITH_ALTERED_SEARCH_PATH is available on unpatched Windows 7;
        # AddDllDirectory would require an additional OS update there.
        self.dll = c.CDLL(os.path.join(directory, 'winpty.dll'), winmode=0x8)
        self.api = WinApi()
        self.pty = self.job = self.process = self.input = None
        self.output = None
        self._terminate_task = None
        self._write_lock = asyncio.Lock()
        definitions = {
            'winpty_config_new': (P, [c.c_ulonglong, P]),
            'winpty_config_set_initial_size': (None, [P, c.c_int, c.c_int]),
            'winpty_config_set_agent_timeout': (None, [P, D]),
            'winpty_config_free': (None, [P]),
            'winpty_open': (P, [P, P]),
            'winpty_agent_process': (P, [P]),
            'winpty_conin_name': (c.c_wchar_p, [P]),
            'winpty_conout_name': (c.c_wchar_p, [P]),
            'winpty_spawn_config_new': (P, [c.c_ulonglong, c.c_wchar_p, c.c_wchar_p, c.c_wchar_p, c.c_wchar_p, P]),
            'winpty_spawn_config_free': (None, [P]),
            'winpty_spawn': (c.c_int, [P, P, P, P, P, P]),
            'winpty_set_size': (c.c_int, [P, c.c_int, c.c_int, P]),
            'winpty_error_msg': (c.c_wchar_p, [P]),
            'winpty_error_free': (None, [P]),
            'winpty_free': (None, [P]),
        }
        for name, (result, args) in definitions.items():
            fn = getattr(self.dll, name)
            fn.restype, fn.argtypes = result, args
        kernel = self.api.kernel
        kernel.GetProcessId.argtypes, kernel.GetProcessId.restype = [P], D
        kernel.WriteFile.argtypes, kernel.WriteFile.restype = [P, P, D, P, P], c.c_int
        kernel.CancelIoEx.argtypes, kernel.CancelIoEx.restype = [P, P], c.c_int
        kernel.TerminateJobObject.argtypes, kernel.TerminateJobObject.restype = [P, D], c.c_int
        kernel.QueryInformationJobObject.argtypes, kernel.QueryInformationJobObject.restype = [P, c.c_int, P, D, P], c.c_int
        try:
            config = self.call('winpty_config_new', 0)
            try:
                self.dll.winpty_config_set_initial_size(config, spec.cols, spec.rows)
                self.dll.winpty_config_set_agent_timeout(config, 10000)
                self.pty = self.call('winpty_open', config)
            finally:
                self.dll.winpty_config_free(config)
            self.job = self.api.check(self.api.CreateJobObjectW(None, None), 'CreateJobObjectW')
            limit = JobLimit()
            limit.basic.flags = 0x2000
            self.api.check(self.api.SetInformationJobObject(self.job, 9, c.byref(limit), c.sizeof(limit)), 'SetInformationJobObject')
            # The agent has no shell child yet. Job membership is inherited by
            # every future console process, preventing child-start races.
            self.api.check(self.api.AssignProcessToJobObject(self.job, self.dll.winpty_agent_process(self.pty)), 'AssignProcessToJobObject')
            self.input = self.open_pipe(self.dll.winpty_conin_name(self.pty), 0x40000000)
            out = self.open_pipe(self.dll.winpty_conout_name(self.pty), 0x80000000)
            import msvcrt
            try:
                fd = msvcrt.open_osfhandle(out, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                self.api.CloseHandle(out)
                raise
            self.output = os.fdopen(fd, 'rb', buffering=0)
            env = '\0'.join('{}={}'.format(key, value) for key, value in sorted(environment.items(), key=lambda row: row[0].upper())) + '\0\0'
            spawn = self.call('winpty_spawn_config_new', 1, spec.argv[0], subprocess.list2cmdline(spec.argv), spec.cwd, env)
            process, process_error = P(), D()
            try:
                self.call('winpty_spawn', self.pty, spawn, c.byref(process), None, c.byref(process_error))
                self.process = process.value
            finally:
                self.dll.winpty_spawn_config_free(spawn)
            self.pid = self.api.check(kernel.GetProcessId(self.process), 'GetProcessId')
            self.done = asyncio.get_running_loop().create_future()
            self._wait_task = asyncio.create_task(self.wait())
        except BaseException:
            self.close_native()
            raise

    def call(self, name, *args):
        error = P()
        result = getattr(self.dll, name)(*args, c.byref(error))
        if error.value:
            try:
                raise RuntimeError(name + ': ' + str(self.dll.winpty_error_msg(error)))
            finally:
                self.dll.winpty_error_free(error)
        if not result:
            raise RuntimeError(name + ' failed')
        return result

    def open_pipe(self, name, access):
        handle = self.api.CreateFileW(name, access, 0, None, 3, 0, None)
        if handle == P(-1).value:
            self.api.error('CreateFileW WinPTY pipe', c.get_last_error())
        return handle

    async def wait(self):
        proactor = getattr(asyncio.get_running_loop(), '_proactor', None)
        wait_for_handle = getattr(proactor, 'wait_for_handle', None)
        try:
            if wait_for_handle is not None:
                # The default Windows loop uses the same IOCP wait for its
                # native subprocesses. The Job still owns descendant teardown.
                await wait_for_handle(self.process)
            else:
                while self.api.WaitForSingleObject(self.process, 0) == 258:
                    await asyncio.sleep(.01)
            code = D()
            self.api.check(self.api.GetExitCodeProcess(self.process, c.byref(code)), 'GetExitCodeProcess')
        except Exception as error:
            if not self.done.done():
                self.done.set_exception(error)
        else:
            if not self.done.done():
                self.done.set_result(SubprocessOutcome(exit_code=code.value, signal=None))

    async def write(self, data):
        async with self._write_lock:
            if self.input is None or self.done.done():
                raise RuntimeError('terminal process has exited')
            raw, handle = data.encode('utf-8'), self.input
            def write_all():
                offset = 0
                while offset < len(raw):
                    chunk = c.create_string_buffer(raw[offset:offset + 4096])
                    size = D()
                    self.api.check(self.api.kernel.WriteFile(handle, chunk, len(chunk) - 1, c.byref(size), None), 'WriteFile WinPTY')
                    if not size.value:
                        raise RuntimeError('WinPTY write made no progress')
                    offset += size.value
            writing = asyncio.get_running_loop().run_in_executor(None, write_all)
            try:
                await asyncio.shield(writing)
            except asyncio.CancelledError:
                # Cancellation cannot release the handle while its OS write
                # still runs in the executor. Job termination unblocks it.
                await asyncio.gather(writing, return_exceptions=True)
                raise

    async def inspect_foreground(self):
        return None

    async def resize(self, cols, rows):
        async with self._write_lock:
            if self.pty is None or self.done.done():raise RuntimeError('terminal process has exited')
            # The DLL's RPC can wait for its agent. Join it before releasing
            # the same lock that protects winpty_free during termination.
            resizing = asyncio.get_running_loop().run_in_executor(None,self.call,'winpty_set_size',self.pty,cols,rows)
            try:await asyncio.shield(resizing)
            except asyncio.CancelledError:
                await asyncio.gather(resizing,return_exceptions=True);raise

    async def signal_foreground(self, signal_name):
        # Console Ctrl-C is supported, but WinPTY cannot verify a POSIX-style
        # foreground group. Do not fabricate a delivered targetPgid result.
        raise RuntimeError('verified foreground-group signaling is unavailable on WinPTY')

    async def interrupt(self):
        await self.write('\x03')

    def terminate_for_host_exit(self):
        if self.job:
            self.api.kernel.TerminateJobObject(self.job, 1)

    def close_native(self, keep_output=False):
        if self.job:
            self.api.CloseHandle(self.job)
            self.job = None
        if self.input:
            self.api.kernel.CancelIoEx(self.input, None)
            self.api.CloseHandle(self.input)
            self.input = None
        if self.output and not keep_output:
            self.output.close()
            self.output = None
        if self.process:
            self.api.CloseHandle(self.process)
            self.process = None
        if self.pty:
            self.dll.winpty_free(self.pty)
            self.pty = None

    async def terminate(self):
        if self._terminate_task is None:
            self._terminate_task = asyncio.create_task(self._terminate())
            def finished(task):
                if task.cancelled() or task.exception() is not None:self._terminate_task = None
            self._terminate_task.add_done_callback(finished)
        await asyncio.shield(self._terminate_task)

    async def _terminate(self):
        if self.job:
            self.api.check(self.api.kernel.TerminateJobObject(self.job, 1), 'TerminateJobObject')
            values = c.create_string_buffer(48)
            while True:
                self.api.check(self.api.kernel.QueryInformationJobObject(self.job, 1, values, len(values), None), 'QueryInformationJobObject')
                if c.c_ulong.from_buffer(values, 40).value == 0:
                    break
                await asyncio.sleep(.01)
        try:
            await self.done
        finally:
            async with self._write_lock:
                self.close_native(keep_output=getattr(self,'defer_output_close',False))
