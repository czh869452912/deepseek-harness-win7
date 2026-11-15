"""Candidate one-shot PowerShell follows the Session's current directory."""
from dsh.shell.canonical_tool_pwsh import CanonicalToolPwsh


class AuthorizedToolPwsh(CanonicalToolPwsh):
    inject = CanonicalToolPwsh.inject + ['workingDirectory']
    directory_aware = True
