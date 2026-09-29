"""Native directory chooser whose child process belongs to the caller."""
import os
import shutil
import sys
from dsh.cordis.plugin import Plugin
from dsh.core.abort import NEVER_ABORTED
from dsh.host.directory_picker.base import DirectoryPickerService
from dsh.host.native_command import run_native


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
            script = "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.FolderBrowserDialog; try { if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Write($f.SelectedPath) } } finally { $f.Dispose() }"
            output = await run_native('powershell.exe', ['-NoProfile', '-STA', '-Command', script], signal)
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
