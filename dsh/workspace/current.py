"""rc.3 fully qualified Workspace identity and persistence snapshots."""
import os
import re
import sys

from dsh.typert.stores import field
from dsh.workspace.workspace import WorkspaceRegistry, WorkspacePlugin


def platform_of(platform):
    return ('win32' if os.name == 'nt' else sys.platform) if platform is None else platform


def fully_qualified_workspace_path(path, platform=None):
    if platform_of(platform) != 'win32':
        return path.startswith('/')
    return bool(re.match(r'^[a-zA-Z]:[\\/]', path) or re.match(r'^[\\/]{2}[^\\/]+[\\/]+[^\\/]+', path))


def default_workspace_title(path, platform=None):
    if platform_of(platform) != 'win32':
        return path.rstrip('/').rsplit('/', 1)[-1] or ('/' if path.startswith('/') else '')
    base = path[2:] if re.match(r'^[a-zA-Z]:', path) else path
    title = re.split(r'[\\/]', base.rstrip('/\\'))[-1]
    if title:
        return title
    if re.match(r'^[a-zA-Z]:', path):
        return path[:3] if len(path) > 2 and path[2] in '/\\' else path[:2]
    return path[:1] if path.startswith(('/', '\\')) else ''


def realpath_normalize(path):
    if not fully_qualified_workspace_path(path):
        raise TypeError("Workspace path is not fully qualified: '%s'" % path)
    # exists()/isdir() suppress permission, ENOTDIR and symlink-loop failures.
    # The current registry may exempt only an actual ENOENT from projection.
    os.stat(path)
    return os.path.normpath(os.path.realpath(path))


class CurrentWorkspaceRegistry(WorkspaceRegistry):
    _normalize_path = staticmethod(realpath_normalize)
    _default_title = staticmethod(default_workspace_title)

    async def _list_stored_headers(self):
        return [field(snapshot, 'header') for snapshot in await self.ctx.get('sessionPersistence').list()]


class CurrentWorkspacePlugin(WorkspacePlugin):
    registry_class = CurrentWorkspaceRegistry
