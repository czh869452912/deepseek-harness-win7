"""Current shell-free desktop intents over Python 3.8 / Windows 7 primitives."""
import asyncio
import ntpath
import os
import platform
import re
import sys
from urllib.parse import quote

from dsh.subprocess.service import scrubbed_parent_env


async def run_native_command(command, args, signal):
    signal.throwIfAborted()
    process = await asyncio.create_subprocess_exec(command, *args, env=scrubbed_parent_env(),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **(dict(creationflags=0x08000000) if os.name == 'nt' else {}))
    def stop(*_):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    release = signal.add_listener('abort', stop)
    try:
        stdout, stderr = await process.communicate()
        signal.throwIfAborted()
        result = dict(stdout=stdout.decode('utf-8', 'replace'), stderr=stderr.decode('utf-8', 'replace'))
        if process.returncode:
            error = RuntimeError('Command failed: {} {}\n{}'.format(command, ' '.join(args), result['stderr']))
            error.code, error.stdout, error.stderr = process.returncode, result['stdout'], result['stderr']
            raise error
        return result
    finally:
        release(); stop()
        await process.wait()


def facts(internals=None):
    options = internals or {}
    return options.get('platform', sys.platform), options.get('env', os.environ), options.get('run', run_native_command), options


def is_wsl(env, options):
    return bool(env.get('WSL_DISTRO_NAME') or env.get('WSL_INTEROP') or 'microsoft' in options.get('osRelease', platform.release()).lower())


def can_open_native_path(internals=None):
    target, env, _, options = facts(internals)
    return target in ('win32', 'darwin') or target == 'linux' and bool(is_wsl(env, options) or env.get('DISPLAY') or env.get('WAYLAND_DISPLAY'))


def native_file_manager(internals=None):
    target, env, _, options = facts(internals)
    return 'finder' if target == 'darwin' else 'explorer' if target == 'win32' or target == 'linux' and is_wsl(env, options) else 'directory' if target == 'linux' else None


async def windows_path(path, signal, run):
    await run('powershell.exe', ['-NoProfile', '-Command', "Invoke-Item -LiteralPath '{}'".format(path.replace("'", "''"))], signal)


async def translate(path, signal, run):
    result = await run('wslpath', ['-w', path], signal)
    signal.throwIfAborted()
    path = result['stdout'].rstrip('\r\n')
    if not path:
        raise RuntimeError('wslpath returned no Windows path')
    return path


async def open_native_path(path, signal, internals=None, text_editor=False):
    target, env, run, options = facts(internals)
    wsl = target == 'linux' and is_wsl(env, options)
    if not wsl and not text_editor and os.path.splitext(path)[1].lower() in ('.html', '.htm', '.xhtml', '.svg'):
        if target == 'darwin':
            bundle = None
            try:
                result = await run('defaults', ['read', 'com.apple.LaunchServices/com.apple.launchservices.secure'], signal)
                plist = re.sub(r'LSHandlerPreferredVersions\s*=\s*\{[^}]*\};', '', result['stdout'])
                block = re.search(r'\{[^{}]*LSHandlerURLScheme\s*=\s*"?https"?;[^{}]*\}', plist)
                bundle = re.search(r'LSHandlerRoleAll\s*=\s*"?([\w.-]+)"?;', block.group()) if block else None
            except Exception:
                pass
            if bundle is not None:
                await run('open', ['-b', bundle.group(1), path], signal)
                return
        elif target == 'linux' and env.get('BROWSER'):
            await run(env['BROWSER'], [path], signal)
            return
    if target == 'darwin':
        await run('open', (['-t'] if text_editor else []) + [path], signal)
    elif target == 'win32':
        await windows_path(path, signal, run)
    elif target == 'linux':
        if wsl:
            await windows_path(await translate(path, signal, run), signal, run)
        else:
            await run('xdg-open', [path], signal)
    else:
        raise RuntimeError('native path opener is unsupported on ' + target)


async def open_native_text_file(path, signal, internals=None):
    await open_native_path(path, signal, internals, text_editor=True)


async def open_native_associated_path(path, signal, internals=None):
    """Use the OS file association for an explicit desktop open gesture."""
    signal.throwIfAborted()
    target, env, run, options = facts(internals)
    if target == 'darwin':
        await run('open', [path], signal)
    elif target == 'win32':
        await windows_path(path, signal, run)
    elif target == 'linux':
        if is_wsl(env, options):
            await windows_path(await translate(path, signal, run), signal, run)
        else:
            await run('xdg-open', [path], signal)
    else:
        raise RuntimeError('native path opener is unsupported on ' + target)


def windows_file_uri(path):
    """Windows pathToFileURL: preserve URL-path punctuation, IDNA UNC authority."""
    normalized = ntpath.abspath(path).replace('\\', '/')
    if normalized.startswith('//'):
        host, _, tail = normalized[2:].partition('/')
        host = host.encode('idna').decode('ascii').lower()
        return 'file://' + ('' if host == 'localhost' else host) + '/' + quote(tail, safe="/:!$&'()*+;=@~")
    return 'file:///' + quote(normalized, safe="/:!$&'()*+;=@~")


async def reveal_native_path(path, signal, internals=None):
    signal.throwIfAborted()
    target, _, run, options = facts(internals)
    manager = native_file_manager(options)
    if manager == 'finder':
        await run('open', ['-R', path], signal)
    elif manager == 'explorer':
        windows = await translate(path, signal, run) if target == 'linux' else path
        uri = windows_file_uri(windows)
        try:
            await run('explorer.exe', ['/select,', uri], signal)
        except Exception as error:
            signal.throwIfAborted()
            if type(getattr(error, 'code', None)) is not int or error.code != 1:
                raise
    elif manager == 'directory':
        await run('xdg-open', [os.path.dirname(path)], signal)
    else:
        raise RuntimeError('native file manager is unsupported on ' + target)
