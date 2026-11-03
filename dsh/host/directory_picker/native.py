"""Native directory chooser whose child process belongs to the caller."""
import os
import shutil
import sys
from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.host.directory_picker.base import DirectoryPickerService
from dsh.host.native_command import run_native


# The PowerShell child has no browser HWND. Give its modal dialog a temporary
# topmost owner instead of relying on foreground activation across processes.
# Use only WinForms APIs available with the Win7 PowerShell 2.0 CLR.
WINDOWS_PICKER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$dialog = $null
try {
    $owner.ShowInTaskbar = $false
    $owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
    $owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $owner.Width = 1
    $owner.Height = 1
    $owner.Opacity = 0
    $owner.TopMost = $true
    $owner.Show()
    [void]$owner.Activate()
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::Write($dialog.SelectedPath)
    }
} finally {
    if ($dialog) { $dialog.Dispose() }
    $owner.Dispose()
}
"""


class NativeDirectoryPickerService(DirectoryPickerService):
    def __init__(self, ctx):
        super().__init__(ctx)
        self._capability = dict(kind='native', pick=self.pick_native)

    def capability(self):
        return self._capability

    async def pick_native(self, signal=NEVER_ABORTED):
        if sys.platform == 'win32':
            # System WinForms is available on Windows 7; no Tk runtime or
            # detached UI thread can survive cancellation of this child.
            output = await run_native('powershell.exe', ['-NoProfile', '-STA', '-Command', WINDOWS_PICKER_SCRIPT], signal)
        elif sys.platform == 'darwin':
            output = await run_native('osascript', ['-e', 'try\nPOSIX path of (choose folder)\non error number -128\nreturn ""\nend try'], signal)
        else:
            command = 'zenity' if shutil.which('zenity') else 'kdialog'
            args = ['--file-selection', '--directory'] if command == 'zenity' else ['--getexistingdirectory', os.path.expanduser('~')]
            try:
                output = await run_native(command, args, signal)
            except RuntimeError as error:
                signal.throw_if_aborted()
                if str(error) == command + ' exited with 1':
                    return None
                raise
        selected = output.rstrip('\r\n')
        return os.path.normpath(selected) if selected else None


class NativeDirectoryPickerPlugin(Plugin):
    id = 'host-directory-picker-native'
    name = '@deepseek-ai/dsh-host-directory-picker-native'

    def apply(self, ctx):
        NativeDirectoryPickerService(ctx)
