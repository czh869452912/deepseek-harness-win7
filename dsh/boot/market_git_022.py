"""Bounded binary Git execution with an owned Windows Job (Python 3.8 / Win7)."""
import asyncio
import os
import shutil
import signal as signals
import subprocess
import threading

from dsh.core.abort import NEVER_ABORTED
from dsh.subprocess.service import scrubbed_parent_env


def git_environment():
    env = {key: value for key, value in scrubbed_parent_env().items()
           if not key.startswith('GIT_') or key in ('GIT_SSH', 'GIT_SSH_COMMAND')}
    if 'GIT_SSH' not in env and 'GIT_SSH_COMMAND' not in env:
        env['GIT_SSH_COMMAND'] = 'ssh -o BatchMode=yes'
    env.update(LC_ALL='C', GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='', SSH_ASKPASS='',
               SSH_ASKPASS_REQUIRE='never', GCM_INTERACTIVE='never', GIT_LFS_SKIP_SMUDGE='1', GIT_LITERAL_PATHSPECS='1')
    return env


async def execute_git(args, cwd, signal, lifetime, timeout_ms, max_stdout, max_stderr,
                      transports, stop=NEVER_ABORTED):
    signal.throwIfAborted()
    lifetime.throwIfAborted()
    safety = ['core.askPass=', 'core.hooksPath=/dev/null', 'core.fsmonitor=false', 'submodule.recurse=false',
              'gc.auto=0', 'maintenance.auto=false', 'protocol.allow=never']
    safety += ['protocol.'+transport+'.allow=always' for transport in transports]
    env = git_environment()
    executable = shutil.which('git', path=env.get('PATH', ''))
    if executable is None:
        return dict(stdout=b'', failed=True, overflowed=False, diagnostic='git: executable not found')
    argv = [executable]+[part for setting in safety for part in ('-c', setting)]+list(args)
    try:
        if os.name == 'nt':
            from dsh.subprocess.windows_process import WindowsJobProcess
            process = WindowsJobProcess(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    except OSError as error:
        return dict(stdout=b'', failed=True, overflowed=False, diagnostic=str(error))
    loop, gate = asyncio.get_running_loop(), threading.Lock()
    state = dict(closed=False, overflow=False, timedOut=False)

    def kill(*_):
        with gate:
            if state['closed']:
                return
            try:
                if os.name == 'nt':
                    process.kill_range()
                else:
                    os.killpg(process.pid, signals.SIGKILL)
            except ProcessLookupError:
                pass

    def read(stream, limit):
        output = bytearray()
        try:
            while True:
                chunk = stream.read(min(65536, max(1, limit+1-len(output))))
                if not chunk:
                    return bytes(output)
                output.extend(chunk)
                if len(output) > limit:
                    state['overflow'] = True
                    kill()
                    return bytes(output[:limit])
        finally:
            stream.close()

    stdout = loop.run_in_executor(None, read, process.stdout, max_stdout)
    stderr = loop.run_in_executor(None, read, process.stderr, max_stderr)
    exited = loop.run_in_executor(None, process.wait)
    detach = [item.add_listener('abort', kill) for item in (signal, lifetime, stop)]

    def expire():
        state['timedOut'] = True
        kill()
    timer = loop.call_later(timeout_ms/1000, expire)

    async def complete():
        code = await exited
        # A completed launcher can leave a credential/helper descendant holding
        # a pipe. The Job still owns it; end that range before joining readers.
        kill()
        out, err = await asyncio.gather(stdout, stderr)
        return code, out, err

    closing = asyncio.create_task(complete())
    try:
        code, out, err = await asyncio.shield(closing)
        signal.throwIfAborted()
        lifetime.throwIfAborted()
        failed = code != 0 or state['overflow'] or state['timedOut'] or stop.aborted
        diagnostic = ('Command timed out' if state['timedOut'] else 'Command output exceeded maxBuffer' if state['overflow']
                      else 'Command failed with exit code '+str(code) if failed else 'undefined')
        return dict(stdout=out, failed=failed, overflowed=state['overflow'] and len(out) >= max_stdout,
                    diagnostic=diagnostic+'\n'+err.decode('utf-8', 'replace').strip())
    finally:
        timer.cancel()
        for release in detach:
            release()
        kill()
        # Repeated Task.cancel() cannot abandon an allocated process or reader.
        try:
            while not closing.done():
                try:
                    await asyncio.shield(closing)
                except asyncio.CancelledError:
                    continue
            closing.result()
        finally:
            with gate:
                state['closed'] = True
                if os.name == 'nt':
                    process.close_handles()
