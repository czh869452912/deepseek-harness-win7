"""Candidate terminal launches follow the exact owner's current directory."""
from dsh.terminal.local import LocalTerminalPlugin
from dsh.terminal.persistent_authorized import AuthorizedPersistentPwsh


class AuthorizedLocalTerminalPlugin(LocalTerminalPlugin):
    inject = LocalTerminalPlugin.inject + ['workingDirectory']
    directory_aware = True


class AuthorizedPersistentPwshPlugin(AuthorizedPersistentPwsh):
    pass
