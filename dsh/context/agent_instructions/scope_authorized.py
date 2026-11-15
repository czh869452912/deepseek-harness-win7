"""Logical instruction namespaces, independent of physical home directories."""
import os
import re

USER_GLOBAL_DIRECTORY = 'user-global'
AGENTS_GLOBAL_DIRECTORY = 'agents-global'
USER_GLOBAL_DIRECTORIES = (USER_GLOBAL_DIRECTORY, AGENTS_GLOBAL_DIRECTORY)
USER_GLOBAL_FILE = 'AGENTS.md'


def _separator(character):
    return character in '/\\' if os.name == 'nt' else character == '/'


def _dirname(path):
    # Preserve spelling and dot components as node:path does; normalizing here
    # would merge distinct logical scope keys before filesystem resolution.
    if not path:return '.'
    root = offset = 0
    if _separator(path[0]):
        root = offset = 1
        if os.name == 'nt' and len(path) > 2 and _separator(path[1]):
            match = re.match(r'^[\\/]{2}[^\\/]+[\\/]+[^\\/]+', path)
            if match:
                if match.end() == len(path):return path
                root = offset = match.end() + 1
    elif os.name == 'nt' and len(path) > 1 and path[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' and path[1] == ':':
        root = offset = 3 if len(path) > 2 and _separator(path[2]) else 2
    matched = True
    for index in range(len(path) - 1, offset - 1, -1):
        if _separator(path[index]):
            if not matched:return path[:index]
        else:matched = False
    return path[:root] if root else '.'


def _basename(path):
    start = 2 if os.name == 'nt' and len(path) > 1 and path[0] in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' and path[1] == ':' else 0
    end = len(path)
    while end > start and _separator(path[end-1]):end -= 1
    begin = end
    while begin > start and not _separator(path[begin-1]):begin -= 1
    return path[begin:end]


def scope_for_display_path(path):
    if path in ('~/.dsh/AGENTS.md', '$DSH_HOME/AGENTS.md'):return USER_GLOBAL_DIRECTORY
    if path in ('~/.agents/AGENTS.md', '$DSH_AGENTS_HOME/AGENTS.md'):return AGENTS_GLOBAL_DIRECTORY
    return _dirname(path)


def is_user_global_directory(directory):
    return directory in USER_GLOBAL_DIRECTORIES


def instruction_candidate_group(directory):
    return USER_GLOBAL_DIRECTORY if directory == AGENTS_GLOBAL_DIRECTORY else directory


def escape_project_display_path(path):
    first = re.split(r'[\\/]', path, maxsplit=1)[0]
    return '.' + os.sep + path if first in USER_GLOBAL_DIRECTORIES else path


def candidate_scope_key(directory, candidate):
    return directory + '\0' + candidate


def instruction_scope_key(path):
    return candidate_scope_key(scope_for_display_path(path), _basename(path))


def decode_scope_key(scope):
    directory, separator, candidate = scope.partition('\0')
    return dict(directory=directory, candidateName=candidate if separator else '')
