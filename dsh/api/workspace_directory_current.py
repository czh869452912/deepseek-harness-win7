"""First-use Documents policy using cancellable hidden Win7 native commands."""
import ntpath
import os
import posixpath
import re
import sys

from dsh.host.native_command_current import run_native_command
from dsh.workspace.current import fully_qualified_workspace_path


def validate_documents_directory(directory,platform=None):
    platform=sys.platform if platform is None else platform
    if not fully_qualified_workspace_path(directory,platform):
        raise ValueError("Documents directory must be fully qualified: '%s'"%directory)
    paths=ntpath if platform=='win32' else posixpath
    result=paths.normpath(directory)
    if platform!='win32':result='/'+result.lstrip('/')
    # Node normalize preserves a trailing separator and the UNC share root.
    unc_root=platform=='win32' and result.startswith('\\\\') and not ntpath.splitdrive(result)[1]
    if (directory.endswith(('\\','/')) if platform=='win32' else directory.endswith('/')) or unc_root:
        if not result.endswith(paths.sep):result+=paths.sep
    return result


async def default_workspace_directory(documents_directory,signal,internals=None):
    internals=internals or {};platform=internals.get('platform',sys.platform)
    paths=ntpath if platform=='win32' else posixpath
    signal.throwIfAborted();directory=documents_directory
    if directory is None:
        if platform=='darwin':command,args='osascript',['-e','POSIX path of (path to documents folder from user domain without folder creation)']
        elif platform=='win32':
            # LEGAL_ADAPTATION: New-Object works on PowerShell 2, unlike ::new().
            command,args='powershell.exe',['-NoLogo','-NoProfile','-NonInteractive','-Command',
                '[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; '
                '[Environment]::GetFolderPath([Environment+SpecialFolder]::MyDocuments, '
                '[Environment+SpecialFolderOption]::DoNotVerify)']
        elif platform=='linux':command,args='xdg-user-dir',['DOCUMENTS']
        else:raise RuntimeError('system Documents directory is unavailable on '+platform)
        run=internals.get('run')
        result=await run(command,args,signal,'hidden') if run is not None else await run_native_command(command,args,signal)
        directory=re.sub(r'[\r\n]+$','',result['stdout'])
        if not directory or (platform=='linux' and paths.normpath(directory)==internals.get('home',os.path.expanduser('~'))):
            raise RuntimeError('system Documents directory is unavailable')
    directory=validate_documents_directory(directory,platform);signal.throwIfAborted()
    return paths.join(directory,'deepseek-harness','default-workspace')
