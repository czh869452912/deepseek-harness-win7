"""Durable Workspace registry, initialized before its service is published."""
import asyncio
from datetime import datetime, timezone
import logging
import os
import uuid

from dsh.cordis.plugin import Plugin
from dsh.workspace.entity import WorkspaceEntity, WorkspaceEntityHost, WorkspaceMoveInvalidError, field, now_iso
from dsh.workspace.paths import realpath_normalize
from dsh.workspace.spec import workspace_domain_spec


class WorkspaceUnknownSessionError(Exception):
    def __init__(self, session_id):
        super().__init__("cannot archive session '%s': live sessions and session persistence hold no such session" % session_id)
        self.session_id = session_id


class WorkspaceOrderInvalidError(Exception):
    def __init__(self, workspace_id):
        super().__init__("cannot reorder unknown workspace '%s'" % workspace_id)
        self.workspace_id = workspace_id


class WorkspaceRegistry:
    def __init__(self, ctx):
        self.ctx = ctx
        self._state, self._table, self._global = None, None, None
        self._entities, self._headers, self._session_paths, self._invalid_session_paths = {}, {}, {}, {}
        self._lock = asyncio.Lock()
        self._host = WorkspaceEntityHost(lambda: self._table, lambda sid: self._session_paths.get(sid),
                                         self._read_session_header, self._remember_session_path)

    async def init(self):
        domain = await self.ctx.get('storageDomain').open(workspace_domain_spec)
        self.ctx.effect(lambda: domain.close)
        self._table, self._global = domain.table('workspaces'), domain.global_handle
        self._state = self._global.get()
        await self._recover_pending_mutation()
        self._validate_stored_state()
        if not self._state['initialized'] or self._table.size:
            await self._index_headers(await self.ctx.get('sessionPersistence').list())
        if not self._state['initialized']:
            await self._bootstrap()
        sessions = self.ctx.get('sessions')
        if sessions is not None:
            await self._index_headers([session.header for session in sessions.list()])
        self._validate_stored_state()
        for identity in self._state['workspaceIds']:
            self._entities[identity] = WorkspaceEntity(self._host, identity, self._table.get(identity))

    async def _set_state(self, state):
        await self._global.set(state)
        self._state = state

    async def _recover_pending_mutation(self):
        pending = self._state.get('pendingMutation')
        if pending is None:
            return
        identity = pending['workspaceId']
        if identity in self._state['workspaceIds']:
            raise ValueError("workspace domain is inconsistent: pending workspace '%s' is still present in registry order" % identity)
        await self._table.delete(identity)
        await self._set_state(dict(self._state, pendingMutation=None))

    def _validate_stored_state(self):
        order = self._state['workspaceIds']
        if len(order) != len(set(order)):
            raise ValueError('workspace domain is inconsistent: registry order repeats workspace')
        if any(self._table.get(identity) is None for identity in order):
            raise ValueError('workspace domain is inconsistent: registry order references missing workspace')
        if self._state['initialized'] and set(order) != set(self._table.keys()):
            raise ValueError('workspace domain is inconsistent: workspace is absent from registry order')
        paths, accounted = set(), set()
        for identity, record in self._table.entries():
            if record['path'] in paths:
                raise ValueError('workspace domain is inconsistent: path is claimed by multiple workspaces')
            paths.add(record['path'])
            for sid in record['sessionIds']:
                if sid in accounted:
                    raise ValueError('workspace domain is inconsistent: session is accounted by multiple workspaces')
                accounted.add(sid)

    async def create(self, path, title=None):
        canonical = realpath_normalize(path)
        if not os.path.isdir(canonical):
            raise ValueError("cannot create a workspace at '%s': path is not a directory" % canonical)
        async with self._lock:
            await self._recover_pending_mutation()
            for entity in self._entities.values():
                if entity.path == canonical:
                    return entity
            identity, now = str(uuid.uuid4()), now_iso()
            record = dict(path=canonical, title=title if title is not None else os.path.basename(canonical), sessionIds=[], createdAt=now, updatedAt=now)
            entity = WorkspaceEntity(self._host, identity, record)
            state = self._state
            self._entities[identity] = entity
            try:
                await self._set_state(dict(state, pendingMutation=dict(operation='create', workspaceId=identity)))
            except BaseException:
                self._entities.pop(identity, None)
                raise
            try:
                await self._table.put(identity, record)
                await self._set_state(dict(state, initialized=True, workspaceIds=[identity] + state['workspaceIds'], pendingMutation=None))
            except BaseException:
                self._entities.pop(identity, None)
                await self._table.delete(identity)
                await self._set_state(state)
                raise
            return entity

    def get(self, identity):
        return self._entities.get(identity)

    def list(self):
        return [self._entities[identity] for identity in self._state['workspaceIds']]

    list_workspaces = list

    async def resolveByPath(self, path):
        canonical = realpath_normalize(path)
        return next((entity for entity in self._entities.values() if entity.path == canonical), None)

    resolve_by_path = resolveByPath
    get_by_path = resolveByPath

    async def delete(self, identity):
        async with self._lock:
            await self._recover_pending_mutation()
            entity = self.get(identity)
            if entity is None:
                return False
            state = self._state
            next_state = dict(state, workspaceIds=[key for key in state['workspaceIds'] if key != identity], pendingMutation=None)
            await self._set_state(dict(next_state, pendingMutation=dict(operation='delete', workspaceId=identity)))
            self._entities.pop(identity)
            try:
                await self._table.delete(identity)
            except BaseException:
                self._entities[identity] = entity
                try:
                    await self._set_state(state)
                except BaseException:
                    self._entities.pop(identity, None)
                    raise
                raise
            try:
                await self._set_state(next_state)
            except Exception as error:
                logging.getLogger('workspace').warning('deleted workspace pending marker cleanup failed: %s', error)
            return True

    async def insertBefore(self, identity, before_id=None):
        async with self._lock:
            await self._recover_pending_mutation()
            order = self._state['workspaceIds']
            for key in (identity, before_id):
                if key is not None and key not in order:
                    raise WorkspaceOrderInvalidError(key)
            if identity == before_id:
                return list(order)
            moved = [key for key in order if key != identity]
            moved.insert(len(moved) if before_id is None else moved.index(before_id), identity)
            if moved != order:
                await self._set_state(dict(self._state, workspaceIds=moved))
            return moved

    insert_before = insertBefore

    @property
    def archivedSessionIds(self):
        return list(self._state['archivedSessionIds'])

    archived_session_ids = archivedSessionIds

    async def archiveSession(self, sid):
        async with self._lock:
            await self._recover_pending_mutation()
            if sid in self.archivedSessionIds:
                return
            sessions = self.ctx.get('sessions')
            if not (sessions is not None and sessions.get(sid) is not None) and sid not in self._headers:
                await self._index_headers(await self.ctx.get('sessionPersistence').list())
                if sid not in self._headers:
                    raise WorkspaceUnknownSessionError(sid)
            await self._set_state(dict(self._state, archivedSessionIds=self.archivedSessionIds + [sid]))

    archive_session = archiveSession

    def _remember_session_path(self, sid, path):
        self._session_paths[sid] = path
        self._invalid_session_paths.pop(sid, None)

    async def _index_headers(self, headers):
        for header in headers:
            sid, cwd = field(header, 'id'), field(header, 'cwd')
            self._headers[sid] = header
            self._session_paths.pop(sid, None)
            try:
                canonical = realpath_normalize(cwd) if cwd is not None else None
                if canonical is None or not os.path.isdir(canonical):
                    raise ValueError('cwd is not a directory')
                self._remember_session_path(sid, canonical)
            except (OSError, ValueError, TypeError) as error:
                self._invalid_session_paths[sid] = str(error)

    async def _read_session_header(self, sid):
        sessions = self.ctx.get('sessions')
        live = sessions.get(sid) if sessions is not None else None
        if live is not None:
            self._headers[sid] = live.header
            return live.header
        if sid not in self._headers:
            await self._index_headers(await self.ctx.get('sessionPersistence').list())
        if sid not in self._headers:
            raise ValueError("cannot validate session '%s': session persistence holds no such session" % sid)
        return self._headers[sid]

    async def _bootstrap(self):
        groups = {}
        for sid, path in self._session_paths.items():
            groups.setdefault(path, []).append(self._headers[sid])
        for headers in groups.values():
            headers.sort(key=lambda h: (-field(h, 'createdAt', 0), field(h, 'id')))
        by_path = {record['path']: identity for identity, record in self._table.entries()}
        accounted = {sid: identity for identity, record in self._table.entries() for sid in record['sessionIds']}
        for path, headers in sorted(groups.items(), key=lambda item: (-field(item[1][0], 'createdAt', 0), item[0])):
            identity = by_path.get(path)
            ids = [field(h, 'id') for h in headers if field(h, 'id') not in accounted or identity is not None and accounted[field(h, 'id')] == identity]
            if identity is None:
                if not ids:
                    continue
                identity = str(uuid.uuid4())
                now = datetime.fromtimestamp(field(headers[0], 'createdAt', 0) / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
                await self._table.put(identity, dict(path=path, title=os.path.basename(path), sessionIds=ids, createdAt=now, updatedAt=now))
            else:
                record = self._table.get(identity)
                ids += [sid for sid in record['sessionIds'] if sid not in ids]
                if ids != record['sessionIds']:
                    await self._table.update(identity, lambda record: dict(record, sessionIds=ids, updatedAt=now_iso()))
            for sid in ids:
                accounted[sid] = identity
        ranks = {path: field(headers[0], 'createdAt', 0) for path, headers in groups.items()}
        prior = {identity: i for i, identity in enumerate(self._state['workspaceIds'])}
        rows = sorted(self._table.entries(), key=lambda row: (-ranks.get(row[1]['path'], datetime.fromisoformat(row[1]['createdAt'].replace('Z', '+00:00')).timestamp() * 1000), prior.get(row[0], float('inf')), row[0]))
        order = [row[0] for row in rows]
        if order != self._state['workspaceIds']:
            await self._set_state(dict(self._state, workspaceIds=order))
        await self._set_state(dict(self._state, initialized=True))


WorkspaceService = WorkspaceRegistry


class WorkspacePlugin(Plugin):
    id = 'workspace'
    name = '@deepseek-ai/dsh-workspace'
    inject = ['storageDomain', 'sessionPersistence']

    async def apply(self, ctx):
        service = WorkspaceRegistry(ctx)
        await service.init()
        ctx.set_service('workspaceRegistry', service)
        ctx.set_service('workspaces', service)
