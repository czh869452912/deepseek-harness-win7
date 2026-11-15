"""Candidate file tools resolve each Agent call through workingDirectory."""
from dsh.fs.tools_current import CurrentToolFs, CurrentToolFsSearch


class AuthorizedToolFs(CurrentToolFs):
    inject = CurrentToolFs.inject + ['workingDirectory']
    directory_aware = True


class AuthorizedToolFsSearch(CurrentToolFsSearch):
    inject = CurrentToolFsSearch.inject + ['workingDirectory']
    directory_aware = True
