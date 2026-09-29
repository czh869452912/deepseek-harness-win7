"""WinPTY console substrate using its C ABI, with a pre-spawn owned Job.

Uses the DLL shipped by pinned pywinpty 0.5.7, not its socket/thread wrappers.
No ConPTY or post-Win7 APIs are required. Console input-wait inspection remains
unavailable: callers must identify silence as inferred_idle, never stdin_read.
"""
import asyncio
import ctypes as c
import importlib.util
import os
import subprocess

from dsh.sandbox.windows_acl import WinApi, JobLimit, P, D
from dsh.subprocess.types import SubprocessOutcome


class WinPtyTerminalHandle:
    def __init__(self, spec, environment):
        package = importlib.util.find_spec('winpty')
        if package is None:
            raise RuntimeError('Win7 terminal requires pinned pywinpty 0.5.7')
        directory = os.path.dirname(package.origin)
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
        while self.api.WaitForSingleObject(self.process, 0) == 258:
            await asyncio.sleep(.01)
        code = D()
        self.api.check(self.api.GetExitCodeProcess(self.process, c.byref(code)), 'GetExitCodeProcess')
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
            await asyncio.get_running_loop().run_in_executor(None, write_all)

    async def inspect_foreground(self):
        return None

    async def signal_foreground(self, signal_name):
        # Console Ctrl-C is supported, but WinPTY cannot verify a POSIX-style
        # foreground group. Do not fabricate a delivered targetPgid result.
        raise RuntimeError('verified foreground-group signaling is unavailable on WinPTY')

    async def interrupt(self):
        await self.write('\x03')

    def close_native(self):
        if self.job:
            self.api.CloseHandle(self.job)
            self.job = None
        if self.input:
            self.api.kernel.CancelIoEx(self.input, None)
            self.api.CloseHandle(self.input)
            self.input = None
        if self.output:
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
        await self.done
        async with self._write_lock:
            self.close_native()
