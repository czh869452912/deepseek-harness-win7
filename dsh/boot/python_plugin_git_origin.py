"""Validated public, commit-pinned native Git acquisition identities."""
import re
from urllib.parse import quote


def checked_git_origin(record):
    from dsh.boot.python_package_git import git_source
    repository, commit, directory = (record.get(key) for key in ('repository', 'commit', 'directory'))
    if (not isinstance(repository, str) or not isinstance(commit, str)
            or re.fullmatch(r'[0-9a-f]{40}', commit) is None or not isinstance(directory, str)):
        raise ValueError('invalid Git acquisition identity')
    source = git_source('git+' + repository + '#' + commit + ('&path:' + quote(directory, safe='/') if directory else ''))
    if source['repository'] != repository or source['publicRepository'] != repository or source['directory'] != directory:
        raise ValueError('Git acquisition must have a public repository and normalized directory')
    return source


def git_dependency(record):
    source = checked_git_origin(record)
    return 'git+' + source['repository'] + '#' + source['ref'] + ('&path:' + quote(source['directory'], safe='/') if source['directory'] else '')
