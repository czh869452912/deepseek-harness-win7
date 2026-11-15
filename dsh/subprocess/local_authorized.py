"""Candidate execution-environment shell lookup over the local subprocess owner."""
import asyncio
import os
import sys

from dsh.cordis.json_text import stringify_json
from .local import LocalSubprocessRuntime, child_env


class SubprocessExecutableNotFoundError(ValueError):
    name = 'SubprocessExecutableNotFoundError'
    code = 'SUBPROCESS_EXECUTABLE_NOT_FOUND'


def check(signal):
    if signal is not None:signal.throwIfAborted()


class AuthorizedLocalSubprocessRuntime(LocalSubprocessRuntime):
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
