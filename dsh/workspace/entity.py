"""Durable Workspace entities: every mutation commits through the domain chain."""
from datetime import datetime, timezone
import os

from dsh.workspace.paths import realpath_normalize


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


class WorkspaceMoveInvalidError(Exception):
    pass


class WorkspaceEntityHost:
    def __init__(self, table_fn, session_path_fn, read_session_header_fn, remember_session_path_fn):
        self.table = table_fn
        self.session_path = session_path_fn
        self.read_session_header = read_session_header_fn
        self.remember_session_path = remember_session_path_fn


class _Unchanged(Exception):
    pass


class WorkspaceEntity:
    def __init__(self, host, workspace_id, record):
        self._host, self.id, self._record = host, workspace_id, dict(record)

    @property
    def workspace_id(self):
        return self.id

    @property
    def path(self):
        return self._record['path']

    @property
    def title(self):
        return self._record['title']

    @property
    def createdAt(self):
        return self._record['createdAt']

    created_at = createdAt

    @property
    def updatedAt(self):
        return self._record['updatedAt']

    updated_at = updatedAt

    @property
    def sessionIds(self):
        return [sid for sid in self._record['sessionIds'] if self._host.session_path(sid) == self.path]

    session_ids = sessionIds

    async def setTitle(self, title):
        await self._mutate(lambda record: dict(record, title=title))

    set_title = setTitle

    async def attachSession(self, session_id):
        if session_id not in self._record['sessionIds']:
            header = await self._host.read_session_header(session_id)
            cwd = field(header, 'cwd')
            if cwd is None:
                raise ValueError("cannot attach session '%s' to workspace '%s': its stored header carries no cwd to validate against" % (session_id, self.path))
            canonical = realpath_normalize(cwd)
            if not os.path.isdir(canonical) or canonical != self.path:
                raise ValueError("cannot attach session '%s' to workspace '%s': its cwd resolves to '%s'" % (session_id, self.path, canonical))
            self._host.remember_session_path(session_id, canonical)
        await self._mutate(lambda record: record if session_id in record['sessionIds'] else dict(record, sessionIds=[session_id] + record['sessionIds']))

    attach_session = attachSession

    async def insertSessionBefore(self, session_id, before_session_id=None):
        def update(record):
            ids = record['sessionIds']
            if session_id not in ids:
                raise WorkspaceMoveInvalidError("cannot move session '%s' in workspace '%s': the session is not accounted" % (session_id, record['path']))
            if before_session_id is not None and before_session_id not in ids:
                raise WorkspaceMoveInvalidError("cannot move session '%s' before '%s' in workspace '%s': the anchor session is not accounted" % (session_id, before_session_id, record['path']))
            if before_session_id == session_id:
                return record
            moved = [sid for sid in ids if sid != session_id]
            moved.insert(len(moved) if before_session_id is None else moved.index(before_session_id), session_id)
            return record if moved == ids else dict(record, sessionIds=moved)
        await self._mutate(update)

    insert_session_before = insertSessionBefore

    async def detachSession(self, session_id):
        await self._mutate(lambda record: dict(record, sessionIds=[sid for sid in record['sessionIds'] if sid != session_id]) if session_id in record['sessionIds'] else record)

    detach_session = detachSession

    async def status(self):
        return 'ok' if os.path.isdir(self.path) else 'missing-dir'

    async def _mutate(self, fn):
        def update(current):
            changed = fn(current)
            ids = [sid for sid in changed['sessionIds'] if self._host.session_path(sid) == changed['path']]
            if changed is current and len(ids) == len(current['sessionIds']):
                raise _Unchanged()
            return dict(changed, sessionIds=ids, updatedAt=now_iso())
        try:
            self._record = await self._host.table().update(self.id, update)
        except _Unchanged:
            pass

    def to_dict(self):
        return dict(workspaceId=self.id, path=self.path, title=self.title, sessionIds=self.sessionIds,
                    createdAt=self.createdAt, updatedAt=self.updatedAt)
