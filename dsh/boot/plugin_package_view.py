"""Owned package-manager metadata queries, shared by management consumers.

The executable seam accepts an application-owned command and prefix args;
it does not require Node in the Python Portable. The default external pnpm
command remains optional until the Python package backend is composed.
"""
import asyncio
import os
import re
from types import SimpleNamespace

from dsh.cordis import Context
from dsh.core.abort import NEVER_ABORTED
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from dsh.subprocess.types import SubprocessSpawnSpec, SubprocessStdio, SubprocessCollect


def registry_arguments(registry):return [] if registry is None else ['--registry='+registry]


def _strip_final_newline(text):return re.sub(r'\r?\n\Z', '', text)


async def view_profile_package(directory, spec, options):
    argv = [options.get('command', 'pnpm')]+list(options.get('args') or [])+[
        'view', spec]+list(options['fields'])+['--json']+registry_arguments(options.get('registry'))+['--config.fetch-retries=0']
    signal = options.get('signal') or NEVER_ABORTED
    timeout = options['timeoutMs']
    ctx = Context()
    timer = None
    timed_out = [False]
    cancelled = [signal.aborted]
    handle = None
    detach = lambda:None
    try:
        runtime_type = AuthorizedLocalSubprocessRuntime if os.name == 'nt' else LocalSubprocessRuntime
        await ctx.plugin(runtime_type)
        runtime = ctx.get('subprocess')
        if signal.aborted:return dict(exitCode=None, stdout='', stderr='', timedOut=False)
        try:
            if os.name == 'nt':
                handle = runtime.spawn(dict(argv=argv, cwd=directory, graceMs=1000, env=options.get('env'),
                    stdio=dict(stdin='ignore', stdout=dict(maxBytes=100000000), stderr=dict(maxBytes=100000000))))
            else:
                handle = runtime.spawn(SubprocessSpawnSpec(argv, directory,
                    SubprocessStdio('ignore', SubprocessCollect(100000000), SubprocessCollect(100000000)), 1000, env=options.get('env')))
        except Exception as error:
            source = getattr(error, 'cause', None) or error
            code = getattr(source, 'code', None)
            if code is None and isinstance(source, OSError):
                import errno
                code = errno.errorcode.get(source.errno)
            if code is None and getattr(error, 'code', None) == 'SUBPROCESS_SPAWN_NOT_FOUND':code = 'ENOENT'
            cause = SimpleNamespace(message=str(error), code=code)
            return dict(exitCode=None, stdout='', stderr='', timedOut=False, cause=cause)
        def stop(reason):
            cancelled[0] = True
            handle.terminate()
        detach = signal.add_listener('abort', stop)
        def expire():
            timed_out[0] = True
            handle.terminate()
        timer = asyncio.get_running_loop().call_later(timeout/1000, expire)
        try:
            outcome = await asyncio.shield(handle.done)
        except Exception as error:
            source = getattr(error, 'cause', None) or error
            import errno
            code = getattr(source, 'code', None) or (errno.errorcode.get(source.errno) if isinstance(source, OSError) else None)
            return dict(exitCode=None, stdout='', stderr='', timedOut=False,
                        cause=SimpleNamespace(message=str(error), code=code))
        timer.cancel()
        if os.name == 'nt':
            stdout = handle.collected['stdout'].readFrom(0)['text']
            stderr = handle.collected['stderr'].readFrom(0)['text']
            code = outcome['exitCode']
        else:
            stdout = handle.collected.stdout.readFrom(0).text
            stderr = handle.collected.stderr.readFrom(0).text
            code = outcome.exitCode
        return dict(exitCode=None if timed_out[0] or cancelled[0] else code,
            stdout=_strip_final_newline(stdout), stderr=_strip_final_newline(stderr), timedOut=timed_out[0])
    finally:
        if timer is not None:timer.cancel()
        detach()
        await ctx.fiber.dispose()
