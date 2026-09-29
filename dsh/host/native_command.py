"""Cancellable desktop handoff, using only Python 3.8 / Win7 system APIs."""
import asyncio
import os
import platform
import re
import sys

from dsh.subprocess.service import scrubbed_parent_env


async def run_native(command, args, signal):
    signal.throw_if_aborted()
    process = await asyncio.create_subprocess_exec(command, *args,
        env=scrubbed_parent_env(), stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **({'creationflags': 0x08000000} if os.name == 'nt' else {}))
    def abort(*_):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    release = signal.add_listener('abort', abort)
    try:
        stdout, stderr = await process.communicate()
        signal.throw_if_aborted()
        if process.returncode:
            raise RuntimeError(stderr.decode('utf-8', 'replace').strip() or '%s exited with %s' % (command, process.returncode))
        return stdout.decode('utf-8', 'replace')
    finally:
        release()
        abort()
        await process.wait()


def is_wsl():
    return bool(os.environ.get('WSL_DISTRO_NAME') or os.environ.get('WSL_INTEROP') or 'microsoft' in platform.release().lower())


def can_open_path():
    return sys.platform in ('win32', 'darwin') or sys.platform.startswith('linux') and bool(is_wsl() or os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


async def open_windows(path, signal):
    await run_native('powershell.exe', ['-NoProfile', '-Command', "Invoke-Item -LiteralPath '%s'" % path.replace("'", "''")], signal)


async def open_path(path, signal, text_editor=False):
    signal.throw_if_aborted()
    if sys.platform == 'win32':
        await open_windows(path, signal)
        return
    if sys.platform.startswith('linux') and is_wsl():
        translated = (await run_native('wslpath', ['-w', path], signal)).rstrip('\r\n')
        if not translated:
            raise RuntimeError('wslpath returned no Windows path')
        await open_windows(translated, signal)
        return
    if not text_editor and os.path.splitext(path)[1].lower() in ('.html', '.htm', '.xhtml', '.svg'):
        if sys.platform == 'darwin':
            bundle = None
            try:
                plist = await run_native('defaults', ['read', 'com.apple.LaunchServices/com.apple.launchservices.secure'], signal)
                plist = re.sub(r'LSHandlerPreferredVersions\s*=\s*\{[^}]*\};', '', plist)
                block = re.search(r'\{[^{}]*LSHandlerURLScheme\s*=\s*"?https"?;[^{}]*\}', plist)
                bundle = re.search(r'LSHandlerRoleAll\s*=\s*"?([\w.-]+)"?;', block.group()) if block else None
            except Exception:
                signal.throw_if_aborted()
            if bundle:
                await run_native('open', ['-b', bundle.group(1), path], signal)
                return
        elif sys.platform.startswith('linux') and os.environ.get('BROWSER'):
            await run_native(os.environ['BROWSER'], [path], signal)
            return
    if sys.platform == 'darwin':
        await run_native('open', (['-t'] if text_editor else []) + [path], signal)
    elif sys.platform.startswith('linux'):
        await run_native('xdg-open', [path], signal)
    else:
        raise RuntimeError('native path opener is unsupported on ' + sys.platform)


async def open_text_file(path, signal):
    await open_path(path, signal, text_editor=True)
