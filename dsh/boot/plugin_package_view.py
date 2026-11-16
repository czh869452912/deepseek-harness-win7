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
from dsh.host.http_proxy_policy import JS_SPACE
from dsh.subprocess.local import LocalSubprocessRuntime
from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
from dsh.subprocess.types import SubprocessSpawnSpec, SubprocessStdio, SubprocessCollect


def registry_arguments(registry):return [] if registry is None else ['--registry='+registry]


def _strip_final_newline(text):return re.sub(r'\r?\n\Z', '', text)


async def view_profile_package(directory, spec, options):
    argv = [options.get('command', 'pnpm')]+list(options.get('args') or [])+[
        'view', spec]+list(options['fields'])+['--json']+registry_arguments(options.get('registry'))+['--config.fetch-retries=0']
    return await _execute_package_query(directory, argv, options)


async def read_profile_registry(directory, options):
    argv = [options.get('command', 'pnpm')]+list(options.get('args') or [])+['config', 'get', 'registry']
    result = await _execute_package_query(directory, argv, options)
    answer = result['stdout'].strip(JS_SPACE).rsplit('\n', 1)[-1].strip(JS_SPACE) if result['exitCode'] == 0 else ''
    return answer if re.fullmatch(r'https?://[^'+re.escape(JS_SPACE)+r']+', answer) else None


async def _execute_package_query(directory, argv, options):
    signal = options.get('signal') or NEVER_ABORTED
    timeout = options['timeoutMs']
    ctx = Context()
    timer = None
    timed_out = [False]
    cancelled = [signal.aborted]
    handle = None
    pump = None
    sink = options.get('_stderrFile')
    detach = lambda:None
    try:
        runtime_type = AuthorizedLocalSubprocessRuntime if os.name == 'nt' else LocalSubprocessRuntime
        await ctx.plugin(runtime_type)
        runtime = ctx.get('subprocess')
        if signal.aborted:return dict(exitCode=None, stdout='', stderr='', timedOut=False)
        try:
            if os.name == 'nt':
                # CreateProcess searches the parent's PATH, not the supplied
                # child environment. Resolve through the owned runtime first.
                argv = [await runtime.resolve_executable(argv[0], options.get('env'), signal)]+argv[1:]
            stderr_mode = 'pipe' if sink is not None else dict(maxBytes=100000000)
            stdout_mode = 'ignore' if options.get('_discardOutput') or sink is not None else dict(maxBytes=100000000)
            if os.name == 'nt':
                handle = runtime.spawn(dict(argv=argv, cwd=directory, graceMs=1000, env=options.get('env'),
                    stdio=dict(stdin='ignore', stdout=stdout_mode, stderr='ignore' if options.get('_discardOutput') else stderr_mode)))
            else:
                handle = runtime.spawn(SubprocessSpawnSpec(argv, directory,
                    SubprocessStdio('ignore', 'ignore' if stdout_mode == 'ignore' else SubprocessCollect(100000000),
                        'ignore' if options.get('_discardOutput') else 'pipe' if sink is not None else SubprocessCollect(100000000)), 1000, env=options.get('env')))
        except Exception as error:
            source = getattr(error, 'cause', None) or error
            code = getattr(source, 'code', None)
            if code is None and isinstance(source, OSError):
                import errno
                code = errno.errorcode.get(source.errno)
            if code in ('SUBPROCESS_SPAWN_NOT_FOUND', 'SUBPROCESS_EXECUTABLE_NOT_FOUND'):code = 'ENOENT'
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
        if sink is not None:
            def copy_stderr():
                while True:
                    chunk = handle.stderr.read(65536)
                    if not chunk:break
                    sink.write(chunk)
                sink.flush()
            pump = asyncio.get_running_loop().run_in_executor(None, copy_stderr)
        try:
            outcome = await asyncio.shield(handle.done)
        except Exception as error:
            source = getattr(error, 'cause', None) or error
            import errno
            code = getattr(source, 'code', None) or (errno.errorcode.get(source.errno) if isinstance(source, OSError) else None)
            return dict(exitCode=None, stdout='', stderr='', timedOut=False,
                        cause=SimpleNamespace(message=str(error), code=code))
        timer.cancel()
        if pump is not None:await asyncio.shield(pump)
        if os.name == 'nt':
            stdout = handle.collected['stdout'].readFrom(0)['text'] if 'stdout' in handle.collected else ''
            stderr = handle.collected['stderr'].readFrom(0)['text'] if 'stderr' in handle.collected else ''
            code = outcome['exitCode']
        else:
            stdout = handle.collected.stdout.readFrom(0).text if handle.collected.stdout is not None else ''
            stderr = handle.collected.stderr.readFrom(0).text if handle.collected.stderr is not None else ''
            code = outcome.exitCode
        return dict(exitCode=None if timed_out[0] or cancelled[0] else code,
            stdout=_strip_final_newline(stdout), stderr=_strip_final_newline(stderr), timedOut=timed_out[0])
    finally:
        if timer is not None:timer.cancel()
        detach()
        if handle is not None:
            handle.terminate()
            try:await asyncio.shield(handle.done)
            except Exception:pass
            await handle.wait_for_exit()
        await ctx.fiber.dispose()
        if pump is not None:await asyncio.shield(pump)
