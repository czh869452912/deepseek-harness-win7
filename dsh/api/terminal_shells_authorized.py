"""Shell discovery belongs to the target execution environment, never browser PATH."""
import asyncio
import re


def executable_name(path):return re.split(r'[/\\]', path)[-1]


def shell_kind(path):return re.sub(r'\.exe$', '', executable_name(path).lower())


def profile(path):
    kind = shell_kind(path)
    return dict(path=path, name=executable_name(path), args=[] if kind == 'cmd' else ['-NoLogo'] if kind in ('pwsh', 'powershell') else ['-i'])


async def resolve_shell(subprocess, configured, signal):
    shell = configured
    if shell is None:
        environment = await subprocess.terminalEnvironment(signal)
        shell = profile(environment.get('defaultShell') if environment.get('defaultShell') is not None else 'cmd.exe' if environment['platform'] == 'windows' else '/bin/sh')
    path = await subprocess.resolveExecutable(shell['path'], None, signal)
    return dict(shell, path=path)


def find_shell(shells, name):
    kind = shell_kind(name)
    return next((shell for shell in shells if shell_kind(shell['path']) == kind), None)


async def discover_shells(subprocess, configured, candidates, signal):
    preferred = await resolve_shell(subprocess, configured, signal)
    async def resolve(candidate):
        try:return await resolve_shell(subprocess, profile(candidate), signal)
        except Exception as error:
            if getattr(error, 'name', None) == 'SubprocessExecutableNotFoundError':return None
            raise
    found = await asyncio.gather(*[resolve(candidate) for candidate in candidates])
    shells = {}
    for shell in [preferred] + found:
        if shell is None:continue
        kind = shell_kind(shell['path'])
        if kind not in shells:shells[kind] = shell
    return list(shells.values())
