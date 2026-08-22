"""
Package-private workspace entity: single Workspace implementation.
Aligned 1:1 with official `@deepseek-ai/dsh-workspace/src/entity`.
"""

import os
import time
from typing import Any, Callable, Dict, List, Optional
from dsh.workspace.paths import realpath_normalize


class AwaitableResult:
    """Wrap a result value so it can be used directly synchronously AND awaited asynchronously."""

    def __init__(self, value: Any):
        self._value = value

    def __await__(self):
        async def _res():
            return self._value
        return _res().__await__()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._value, name)

    def __bool__(self) -> bool:
        return bool(self._value)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, AwaitableResult):
            return self._value == other._value
        return self._value == other

    def __len__(self) -> int:
        return len(self._value)

    def __iter__(self):
        return iter(self._value)

    def __getitem__(self, item: Any) -> Any:
        return self._value[item]

    def __repr__(self) -> str:
        return repr(self._value)

    def __str__(self) -> str:
        return str(self._value)


class WorkspaceMoveInvalidError(Exception):
    """An insertSessionBefore request named a session or anchor not on the account."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.name = "WorkspaceMoveInvalidError"


class WorkspaceEntityHost:
    """The registry-owned machinery an entity mutates through."""

    def __init__(
        self,
        table_fn: Callable[[], Any],
        session_path_fn: Callable[[str], Optional[str]],
        read_session_header_fn: Callable[[str], Any],
        remember_session_path_fn: Callable[[str, str], None],
    ):
        self.table = table_fn
        self.session_path = session_path_fn
        self.read_session_header = read_session_header_fn
        self.remember_session_path = remember_session_path_fn


class WorkspaceEntity:
    """The single Workspace implementation."""

    def __init__(
        self,
        host: WorkspaceEntityHost,
        workspace_id: str,
        record: Dict[str, Any],
    ):
        self._host = host
        self.id = workspace_id
        self._record = dict(record)

    @property
    def workspace_id(self) -> str:
        return self.id

    @workspace_id.setter
    def workspace_id(self, val: str) -> None:
        self.id = val

    @property
    def path(self) -> str:
        return self._record["path"]

    @property
    def title(self) -> str:
        return self._record["title"]

    @title.setter
    def title(self, val: str) -> None:
        self._record["title"] = val

    @property
    def created_at(self) -> str:
        return self._record["createdAt"]

    @property
    def createdAt(self) -> str:
        return self.created_at

    @property
    def updated_at(self) -> str:
        return self._record["updatedAt"]

    @updated_at.setter
    def updated_at(self, val: str) -> None:
        self._record["updatedAt"] = val

    @property
    def updatedAt(self) -> str:
        return self.updated_at

    @property
    def session_ids(self) -> List[str]:
        raw = self._record.get("sessionIds", [])
        res = []
        for sid in raw:
            sp = self._host.session_path(sid)
            if sp is None or sp == self.path:
                res.append(sid)
        return res

    @session_ids.setter
    def session_ids(self, val: List[str]) -> None:
        self._record["sessionIds"] = list(val)

    @property
    def sessionIds(self) -> List[str]:
        return self.session_ids

    def set_title(self, title: str) -> Any:
        def _update(current: Dict[str, Any]) -> Dict[str, Any]:
            res = dict(current)
            res["title"] = title
            return res

        self._mutate_sync(_update)
        return AwaitableResult(None)

    def setTitle(self, title: str) -> Any:
        return self.set_title(title)

    def attach_session(self, session_id: str) -> Any:
        current_ids = self._record.get("sessionIds", [])
        if session_id not in current_ids:
            try:
                header = self._host.read_session_header(session_id)
            except Exception:
                header = None

            if header:
                cwd = getattr(header, "cwd", None) if header else None
                if cwd is None and isinstance(header, dict):
                    cwd = header.get("cwd")

                if cwd is not None:
                    try:
                        norm_cwd = realpath_normalize(cwd)
                        if norm_cwd == self.path:
                            self._host.remember_session_path(session_id, norm_cwd)
                    except Exception:
                        pass

        def _update(current: Dict[str, Any]) -> Dict[str, Any]:
            s_list = current.get("sessionIds", [])
            if session_id in s_list:
                return current
            res = dict(current)
            res["sessionIds"] = [session_id] + list(s_list)
            return res

        self._mutate_sync(_update)
        return AwaitableResult(None)

    def attachSession(self, session_id: str) -> Any:
        return self.attach_session(session_id)

    def insert_session_before(self, session_id: str, before_session_id: Optional[str] = None) -> Any:
        def _update(current: Dict[str, Any]) -> Dict[str, Any]:
            s_list = current.get("sessionIds", [])
            if session_id not in s_list:
                raise WorkspaceMoveInvalidError(
                    f"cannot move session '{session_id}' in workspace '{current['path']}': the session is not accounted"
                )
            if before_session_id is not None and before_session_id not in s_list:
                raise WorkspaceMoveInvalidError(
                    f"cannot move session '{session_id}' before '{before_session_id}' in workspace '{current['path']}': "
                    "the anchor session is not accounted"
                )
            if before_session_id == session_id:
                return current

            without = [sid for sid in s_list if sid != session_id]
            at = len(without) if before_session_id is None else without.index(before_session_id)
            new_s_list = without[:at] + [session_id] + without[at:]
            if new_s_list == s_list:
                return current
            res = dict(current)
            res["sessionIds"] = new_s_list
            return res

        self._mutate_sync(_update)
        return AwaitableResult(None)

    def insertSessionBefore(self, session_id: str, before_session_id: Optional[str] = None) -> Any:
        return self.insert_session_before(session_id, before_session_id)

    def detach_session(self, session_id: str) -> Any:
        def _update(current: Dict[str, Any]) -> Dict[str, Any]:
            s_list = current.get("sessionIds", [])
            if session_id not in s_list:
                return current
            res = dict(current)
            res["sessionIds"] = [sid for sid in s_list if sid != session_id]
            return res

        self._mutate_sync(_update)
        return AwaitableResult(None)

    def detachSession(self, session_id: str) -> Any:
        return self.detach_session(session_id)

    def status(self) -> Any:
        try:
            res = "ok" if os.path.isdir(self.path) else "missing-dir"
        except Exception:
            res = "missing-dir"
        return AwaitableResult(res)

    def _mutate_sync(self, fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        next_rec = fn(self._record)
        next_rec["updatedAt"] = now_str
        self._record = next_rec

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspaceId": self.id,
            "path": self.path,
            "title": self.title,
            "sessionIds": self.session_ids,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
