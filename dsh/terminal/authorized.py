"""Candidate terminal launches follow the exact owner's current directory."""
from dsh.terminal.local import LocalTerminalPlugin
from dsh.terminal.persistent_pwsh import PersistentPwshPlugin


class AuthorizedLocalTerminalPlugin(LocalTerminalPlugin):
    inject = LocalTerminalPlugin.inject + ['workingDirectory']
    directory_aware = True


class AuthorizedPersistentPwshPlugin(PersistentPwshPlugin):
    inject = PersistentPwshPlugin.inject + ['workingDirectory']
    directory_aware = True
