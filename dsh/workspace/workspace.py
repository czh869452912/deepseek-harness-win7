"""
Workspace entity registry (`ctx.workspaceRegistry` / `ctx.workspaces`).
Aligned 1:1 with official `@deepseek-ai/dsh-workspace/src/index`.
"""

import asyncio
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dsh.cordis.plugin import Plugin
from dsh.workspace.entity import AwaitableResult, WorkspaceEntity, WorkspaceEntityHost, WorkspaceMoveInvalidError
from dsh.workspace.paths import realpath_normalize
from dsh.workspace.spec import workspace_domain_spec


class WorkspaceUnknownSessionError(Exception):
    """An archiveSession request named a session neither live nor in session persistence."""

    def __init__(self, session_id: str):
        super().__init__(f"cannot archive session '{session_id}': live sessions and session persistence hold no such session")
        self.session_id = session_id
        self.name = "WorkspaceUnknownSessionError"


class WorkspaceOrderInvalidError(Exception):
    """A workspace reorder named a source or anchor absent from the durable registry order."""

    def __init__(self, workspace_id: str):
        super().__init__(f"cannot reorder unknown workspace '{workspace_id}'")
        self.workspace_id = workspace_id
        self.name = "WorkspaceOrderInvalidError"


class WorkspaceRegistry:
    """
    Durable workspace registry mounted at `ctx.workspaceRegistry` and `ctx.workspaces`.
    """

    inject = ["storageDomain", "sessionPersistence"]

    def __init__(self, ctx: Any = None):
        self.ctx = ctx
        self._table: Any = None
        self._global: Any = None
        self._state: Optional[Dict[str, Any]] = None
        self._entities: Dict[str, WorkspaceEntity] = {}
        self._headers: Dict[str, Any] = {}
        self._session_paths: Dict[str, str] = {}
        self._invalid_session_paths: Dict[str, str] = {}

        self._in_memory_workspaces: Dict[str, WorkspaceEntity] = {}
        self._in_memory_order: List[str] = []
        self._in_memory_archived: Set[str] = set()

        self._host = WorkspaceEntityHost(
            table_fn=self._require_table,
            session_path_fn=lambda sid: self._session_paths.get(sid),
            read_session_header_fn=self._read_session_header,
            remember_session_path_fn=self._remember_session_path,
        )

    def _require_table(self) -> Any:
        if self._table is not None:
            return self._table

        class DummyTable:
            def __init__(self, registry: "WorkspaceRegistry"):
                self.reg = registry

            async def update(self, key: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
                entity = self.reg._entities.get(key)
                if not entity:
                    raise KeyError(key)
                next_rec = fn(entity._record)
                entity._record = next_rec
                return next_rec

        return DummyTable(self)

    def _remember_session_path(self, sid: str, path: str) -> None:
        self._session_paths[sid] = path
        self._invalid_session_paths.pop(sid, None)

    def _read_session_header(self, sid: str) -> Any:
        sessions_svc = self.ctx.get("sessions") if self.ctx and hasattr(self.ctx, "get") else None
        if sessions_svc:
            live = sessions_svc.get(sid) if hasattr(sessions_svc, "get") else None
            if live:
                hdr = getattr(live, "header", live)
                self._headers[sid] = hdr
                return hdr

        cached = self._headers.get(sid)
        if cached:
            return cached

        persistence = self.ctx.get("sessionPersistence") if self.ctx and hasattr(self.ctx, "get") else None
        if persistence and hasattr(persistence, "list"):
            try:
                headers = persistence.list()
                for h in headers:
                    h_id = getattr(h, "id", None) or (h.get("id") if isinstance(h, dict) else None)
                    if h_id:
                        self._headers[h_id] = h
                if sid in self._headers:
                    return self._headers[sid]
            except Exception:
                pass

        raise ValueError(f"cannot validate session '{sid}': session persistence holds no such session")

    async def init(self) -> None:
        storage_domain = self.ctx.get("storageDomain") if self.ctx and hasattr(self.ctx, "get") else None
        if storage_domain and hasattr(storage_domain, "open"):
            try:
                domain = await storage_domain.open(workspace_domain_spec)
                self._table = domain.table("workspaces")
                self._global = domain.global_handle
                self._state = self._global.get()
                await self._recover_pending_mutation()
                self._validate_stored_state(self._state)

                persistence = self.ctx.get("sessionPersistence") if hasattr(self.ctx, "get") else None
                headers = await persistence.list() if persistence and hasattr(persistence, "list") else []

                if not self._state.get("initialized"):
                    await self._replace_header_index(headers)
                    await self._bootstrap(headers)
                elif self._table.size > 0:
                    await self._replace_header_index(headers)

                await self._index_live_sessions()
                self._rebuild_entities()
                return
            except Exception:
                pass

        if self._state is None:
            self._state = {
                "initialized": True,
                "workspaceIds": [],
                "archivedSessionIds": [],
                "pendingMutation": None,
            }

    def create(self, path: str, title: Optional[str] = None) -> Any:
        canonical = realpath_normalize(path)
        if not os.path.isdir(canonical):
            raise ValueError(f"cannot create a workspace at '{canonical}': path is not a directory")

        for entity in self._entities.values():
            if entity.path == canonical:
                return AwaitableResult(entity)

        for entity in self._in_memory_workspaces.values():
            if entity.path == canonical:
                if title:
                    entity.title = title
                return AwaitableResult(entity)

        ws_id = f"ws-{uuid.uuid4().hex[:8]}"
        ws_name = title or os.path.basename(canonical) or "workspace"
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        record = {
            "path": canonical,
            "title": ws_name,
            "sessionIds": [],
            "createdAt": now_str,
            "updatedAt": now_str,
        }

        entity = WorkspaceEntity(self._host, ws_id, record)
        self._entities[ws_id] = entity
        self._in_memory_workspaces[ws_id] = entity

        if self._state is not None:
            w_ids = [ws_id] + [wid for wid in self._state.get("workspaceIds", []) if wid != ws_id]
            self._state["workspaceIds"] = w_ids
            self._state["initialized"] = True
            if self._global:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._global.set(dict(self._state)))
                except RuntimeError:
                    pass
        if ws_id not in self._in_memory_order:
            self._in_memory_order.insert(0, ws_id)

        if self._table and hasattr(self._table, "put"):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._table.put(ws_id, record))
            except RuntimeError:
                pass

        if self.ctx and hasattr(self.ctx, "emit"):
            try:
                self.ctx.emit("workspace:created", entity.to_dict())
            except Exception:
                pass

        return AwaitableResult(entity)

    def get(self, ws_id: str) -> Optional[WorkspaceEntity]:
        return self._entities.get(ws_id) or self._in_memory_workspaces.get(ws_id)

    def resolve_by_path(self, path: str) -> Optional[WorkspaceEntity]:
        try:
            canonical = realpath_normalize(path)
        except Exception:
            return None
        for entity in list(self._entities.values()) + list(self._in_memory_workspaces.values()):
            if entity.path == canonical:
                return entity
        return None

    def get_by_path(self, path: str) -> Optional[WorkspaceEntity]:
        return self.resolve_by_path(path)

    def resolveByPath(self, path: str) -> Optional[WorkspaceEntity]:
        return self.resolve_by_path(path)

    def list(self) -> List[WorkspaceEntity]:
        order = self._state.get("workspaceIds", []) if self._state else self._in_memory_order
        res = []
        for wid in order:
            ent = self.get(wid)
            if ent:
                res.append(ent)
        return res

    def list_workspaces(self) -> List[WorkspaceEntity]:
        return self.list()

    def delete(self, ws_id: str) -> Any:
        entity = self.get(ws_id)
        if not entity:
            return AwaitableResult(False)

        self._entities.pop(ws_id, None)
        self._in_memory_workspaces.pop(ws_id, None)
        if ws_id in self._in_memory_order:
            self._in_memory_order.remove(ws_id)

        if self._state is not None:
            w_ids = [wid for wid in self._state.get("workspaceIds", []) if wid != ws_id]
            self._state["workspaceIds"] = w_ids
            if self._global:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._global.set(dict(self._state)))
                except RuntimeError:
                    pass

        if self._table and hasattr(self._table, "delete"):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._table.delete(ws_id))
            except RuntimeError:
                pass

        if self.ctx and hasattr(self.ctx, "emit"):
            try:
                self.ctx.emit("workspace:deleted", {"workspaceId": ws_id})
            except Exception:
                pass

        return AwaitableResult(True)

    def insert_before(self, ws_id: str, before_id: Optional[str] = None) -> Any:
        order = list(self._state.get("workspaceIds", []) if self._state else self._in_memory_order)
        if ws_id not in order:
            raise WorkspaceOrderInvalidError(ws_id)
        if before_id is not None and before_id not in order:
            raise WorkspaceOrderInvalidError(before_id)
        if before_id == ws_id:
            return AwaitableResult(order)

        without = [wid for wid in order if wid != ws_id]
        at = len(without) if before_id is None else without.index(before_id)
        new_order = without[:at] + [ws_id] + without[at:]

        if self._state is not None:
            self._state["workspaceIds"] = new_order
            if self._global:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._global.set(dict(self._state)))
                except RuntimeError:
                    pass
        self._in_memory_order = new_order
        return AwaitableResult(new_order)

    def insertBefore(self, ws_id: str, before_id: Optional[str] = None) -> Any:
        return self.insert_before(ws_id, before_id)

    @property
    def archived_session_ids(self) -> List[str]:
        if self._state:
            return list(self._state.get("archivedSessionIds", []))
        return list(self._in_memory_archived)

    @property
    def archivedSessionIds(self) -> List[str]:
        return self.archived_session_ids

    def archive_session(self, session_id: str) -> Any:
        archived = self.archived_session_ids
        if session_id in archived:
            return AwaitableResult(None)

        if not self._session_known(session_id):
            raise WorkspaceUnknownSessionError(session_id)

        if self._state is not None:
            self._state["archivedSessionIds"] = archived + [session_id]
            if self._global:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._global.set(dict(self._state)))
                except RuntimeError:
                    pass
        self._in_memory_archived.add(session_id)
        return AwaitableResult(None)

    def archiveSession(self, session_id: str) -> Any:
        return self.archive_session(session_id)

    def bind_session(self, ws_id: str, session_id: str) -> None:
        ws = self.get(ws_id)
        if ws:
            if session_id not in ws._record.get("sessionIds", []):
                ws._record["sessionIds"].append(session_id)
                ws.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if self.ctx and hasattr(self.ctx, "emit"):
                    try:
                        self.ctx.emit("workspace:session-bound", {"workspaceId": ws_id, "sessionId": session_id})
                    except Exception:
                        pass

    def unbind_session(self, ws_id: str, session_id: str) -> None:
        ws = self.get(ws_id)
        if ws:
            if session_id in ws._record.get("sessionIds", []):
                ws._record["sessionIds"].remove(session_id)
                ws.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if self.ctx and hasattr(self.ctx, "emit"):
                    try:
                        self.ctx.emit("workspace:session-unbound", {"workspaceId": ws_id, "sessionId": session_id})
                    except Exception:
                        pass

    def touch(self, ws_id: str) -> None:
        ws = self.get(ws_id)
        if ws:
            ws.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _session_known(self, session_id: str) -> bool:
        sessions_svc = self.ctx.get("sessions") if self.ctx and hasattr(self.ctx, "get") else None
        if sessions_svc and hasattr(sessions_svc, "get") and sessions_svc.get(session_id) is not None:
            return True
        if session_id in self._headers:
            return True
        return False

    async def _recover_pending_mutation(self) -> None:
        if not self._state:
            return
        pending = self._state.get("pendingMutation")
        if not pending:
            return
        ws_id = pending.get("workspaceId")
        if ws_id in self._state.get("workspaceIds", []):
            raise ValueError(f"workspace domain is inconsistent: pending {pending.get('operation')} workspace '{ws_id}' is still present in registry order")
        if self._table and hasattr(self._table, "delete"):
            await self._table.delete(ws_id)
        self._state["pendingMutation"] = None
        if self._global:
            await self._global.set(dict(self._state))

    def _validate_stored_state(self, state: Dict[str, Any]) -> None:
        order = set()
        for wid in state.get("workspaceIds", []):
            if wid in order:
                raise ValueError(f"workspace domain is inconsistent: registry order repeats workspace '{wid}'")
            order.add(wid)

    def _rebuild_entities(self) -> None:
        self._entities.clear()
        if not self._state or not self._table:
            return
        for wid in self._state.get("workspaceIds", []):
            rec = self._table.get(wid) if hasattr(self._table, "get") else None
            if rec:
                self._entities[wid] = WorkspaceEntity(self._host, wid, rec)

    async def _replace_header_index(self, headers: List[Any]) -> None:
        self._headers.clear()
        self._session_paths.clear()
        self._invalid_session_paths.clear()
        for h in headers:
            h_id = getattr(h, "id", None) or (h.get("id") if isinstance(h, dict) else None)
            cwd = getattr(h, "cwd", None) or (h.get("cwd") if isinstance(h, dict) else None)
            if h_id:
                self._headers[h_id] = h
                if cwd and os.path.isdir(cwd):
                    try:
                        norm = realpath_normalize(cwd)
                        self._session_paths[h_id] = norm
                    except Exception:
                        pass

    async def _bootstrap(self, headers: List[Any]) -> None:
        if not self._state:
            return
        self._state["initialized"] = True
        if self._global:
            await self._global.set(dict(self._state))

    async def _index_live_sessions(self) -> None:
        sessions_svc = self.ctx.get("sessions") if self.ctx and hasattr(self.ctx, "get") else None
        if sessions_svc and hasattr(sessions_svc, "list"):
            headers = [getattr(s, "header", s) for s in sessions_svc.list()]
            await self._replace_header_index(headers)


# Alias for Service
WorkspaceService = WorkspaceRegistry


class WorkspacePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-workspace`: Mounts `ctx.workspaceRegistry` / `ctx.workspaces` service.
    """

    id = "workspace"
    name = "@deepseek-ai/dsh-workspace"

    def apply(self, ctx: Any) -> None:
        svc = WorkspaceRegistry(ctx)
        ctx.set_service("workspaceRegistry", svc)
        ctx.set_service("workspaces", svc)
