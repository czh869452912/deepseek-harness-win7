"""Candidate execution-environment shell lookup over the local subprocess owner."""
import asyncio
import os
import sys

from dsh.cordis.json_text import stringify_json
from .local import LocalSubprocessRuntime, child_env
from .error import SubprocessExecutableNotFoundError


def check(signal):
    if signal is not None:signal.throwIfAborted()


class AuthorizedLocalSubprocessRuntime(LocalSubprocessRuntime):
    owns_windows_job = True

    def __init__(self,ctx):
        super().__init__(ctx)
        self.ordinary_cleanups=set()

    async def _dispose_managed_processes(self):
        await super()._dispose_managed_processes()
        if self.ordinary_cleanups:
            await asyncio.gather(*list(self.ordinary_cleanups))

    def spawn(self,spec):
        if not isinstance(spec,dict):return super().spawn(spec)
        if sys.platform!='win32':raise RuntimeError('Canonical Win7 ordinary process provider requires Windows')
        from .ordinary_authorized import spawn
        return spawn(self,spec)

    async def spawnTerminal(self, spec):
        if not spec.get('argv') or not spec['argv'][0]:
            from dsh.subprocess.error import SubprocessError
            raise SubprocessError('subprocess-local: terminal argv must contain a program','SUBPROCESS_INVALID_ARGV')
        signal=spec.get('signal');check(signal)
        if sys.platform!='win32':raise RuntimeError('Canonical Win7 terminal provider requires Windows')
        from dsh.subprocess.types import SubprocessTerminalSpawnSpec
        from dsh.subprocess.winpty import WinPtyTerminalHandle
        from dsh.subprocess.terminal_authorized import WindowsTerminalHandle
        environment=child_env(spec.get('env'));environment['TERM']=spec['terminalType']
        native=SubprocessTerminalSpawnSpec(spec['argv'],spec['cwd'],spec['rows'],spec['cols'],spec['graceMs'],signal=signal)
        raw=WinPtyTerminalHandle(native,environment)
        try:
            handle=WindowsTerminalHandle(raw,self.terminals.discard)
            self.terminals.add(handle)
        except BaseException:
            raw.defer_output_close=False;await raw.terminate();raise
        # The canonical provider checks cancellation before its synchronous
        # allocation; the controller owns cancellation after publication.
        if not spec.get('shellActivity'):
            def exited(_):
                task=asyncio.ensure_future(handle.terminate())
                task.add_done_callback(lambda done:None if done.cancelled() else done.exception())
            handle.done.add_done_callback(exited)
        return handle

    async def resolve_executable(self, command, env=None, signal=None):
        if not command:raise ValueError('subprocess-local: executable must be non-empty')
        check(signal);environment = child_env(env);absolute = os.path.isabs(command)
        if not absolute and ('/' in command or sys.platform == 'win32' and '\\' in command):
            raise ValueError('subprocess-local: command %s is a relative path; use an absolute path or a bare PATH name' % stringify_json(command))
        candidates = [command] if absolute else self._executable_candidates(command, environment)
        def executable(path):return os.path.isfile(path) and os.access(path, os.X_OK)
        for candidate in candidates:
            check(signal)
            try:valid = await asyncio.get_running_loop().run_in_executor(None, executable, candidate)
            except (OSError, ValueError):continue
            if valid:check(signal);return candidate
        check(signal)
        raise SubprocessExecutableNotFoundError('subprocess-local: command %s %s' %
            (stringify_json(command), 'is not an executable file' if absolute else 'was not found on PATH'))

    async def resolveExecutable(self, command, env=None, signal=None):
        return await self.resolve_executable(command, env, signal)

    async def terminalEnvironment(self, signal=None):
        check(signal);platform = 'windows' if sys.platform == 'win32' else 'posix'
        shell = os.environ.get('ComSpec') if platform == 'windows' else os.environ.get('SHELL')
        if not shell and platform == 'posix':
            import pwd
            shell = pwd.getpwuid(os.getuid()).pw_shell
        return dict(platform=platform, **(dict(defaultShell=shell) if shell else {}))
