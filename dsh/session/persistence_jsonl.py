"""
JSONL durable session-persistence backend for DeepSeek Harness Win7.
Stores SessionHeader on line 1, followed by contiguous SessionEvent lines.
Includes crash recovery (closing interrupted turns) and packed chunk rows.
"""

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional
from dsh.cordis.plugin import Plugin
from dsh.core.session import SessionHeader, SESSION_FORMAT_VERSION
from dsh.session.persistence import (
    SessionInspection,
    SessionLocation,
    SessionPersistence,
    SessionPersistenceSnapshot,
)
from dsh.session.repair import migrate_legacy_event


def _project_dir_name(cwd: Optional[str]) -> str:
    if not cwd:
        return "_default"
    normalized = os.path.normpath(cwd).replace("\\", "/").lower()
    h = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    base = os.path.basename(os.path.normpath(cwd)) or "root"
    safe_base = "".join(c if c.isalnum() or c in "-_" else "_" for c in base)
    return f"{safe_base}_{h}"


class JsonlSessionPersistence(SessionPersistence):
    """
    JSONL durable session-persistence backend.
    """

    def __init__(
        self,
        root: str,
        pack_chunks: bool = True,
        ctx: Optional[Any] = None,
    ):
        super().__init__(ctx=ctx)
        self.root = os.path.abspath(root)
        self.pack_chunks = pack_chunks
        self._pending: Dict[str, List[Dict[str, Any]]] = {}
        self._registered_meta: Dict[str, SessionHeader] = {}

    def _log_path(self, cwd: Optional[str], session_id: str) -> str:
        project_dir = _project_dir_name(cwd)
        return os.path.join(self.root, project_dir, session_id, "session.jsonl")

    def _find_log_path(self, session_id: str) -> Optional[str]:
        if not os.path.exists(self.root):
            return None
        for proj in os.listdir(self.root):
            pdir = os.path.join(self.root, proj)
            if os.path.isdir(pdir):
                candidate = os.path.join(pdir, session_id, "session.jsonl")
                if os.path.isfile(candidate):
                    return candidate
        return None

    def locate(self, meta: SessionHeader) -> SessionLocation:
        path = self._log_path(meta.cwd, meta.id)
        return SessionLocation(kind="jsonl", path=path)

    async def create(self, meta: SessionHeader) -> None:
        self._registered_meta[meta.id] = meta
        path = self.locate(meta).path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            tmp_path = f"{path}.{int(time.time() * 1000)}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                header_line = json.dumps(meta.to_dict(), ensure_ascii=False)
                f.write(header_line + "\n")
                f.flush()
                os.fsync(f.fileno())
            if os.path.exists(path):
                os.remove(tmp_path)
            else:
                os.replace(tmp_path, path)

    async def append(self, session_id: str, events: List[Dict[str, Any]]) -> None:
        if not events:
            return

        meta = self._registered_meta.get(session_id)
        path = self._log_path(meta.cwd if meta else None, session_id)
        if not os.path.exists(path):
            found = self._find_log_path(session_id)
            if found:
                path = found
            else:
                # Materialize header
                if not meta:
                    meta = SessionHeader(session_id=session_id)
                await self.create(meta)

        os.makedirs(os.path.dirname(path), exist_ok=True)

        lines_to_write = self._encode_events(events)
        with open(path, "a", encoding="utf-8") as f:
            for line in lines_to_write:
                f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _encode_events(self, events: List[Dict[str, Any]]) -> List[str]:
        lines: List[str] = []
        if not self.pack_chunks:
            for event in events:
                lines.append(json.dumps(event, ensure_ascii=False))
            return lines

        pending_chunks: List[Dict[str, Any]] = []
        base_seq: Optional[int] = None
        base_time: Optional[int] = None
        session_id: str = ""

        def flush_chunks():
            nonlocal pending_chunks, base_seq, base_time, session_id
            if pending_chunks:
                batch_data = [c.get("data", {}).get("chunk") for c in pending_chunks]
                batch_event = {
                    "type": "assistant/chunk-batch",
                    "seq": base_seq,
                    "time": base_time,
                    "session_id": session_id,
                    "chunks": batch_data,
                }
                lines.append(json.dumps(batch_event, ensure_ascii=False))
                pending_chunks.clear()
                base_seq = None
                base_time = None

        for event in events:
            if event.get("type") == "assistant/chunk":
                if not pending_chunks:
                    base_seq = event.get("seq")
                    base_time = event.get("time")
                    session_id = event.get("session_id", "")
                pending_chunks.append(event)
            else:
                flush_chunks()
                lines.append(json.dumps(event, ensure_ascii=False))
        flush_chunks()
        return lines

    def _decode_events(self, raw_lines: List[str]) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        for line in raw_lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue

            if data.get("type") == "assistant/chunk-batch":
                # Unpack packed chunk row
                base_seq = data.get("seq", len(events))
                chunks = data.get("chunks", [])
                for i, chk in enumerate(chunks):
                    events.append({
                        "type": "assistant/chunk",
                        "seq": base_seq + i,
                        "time": data.get("time", int(time.time() * 1000)),
                        "session_id": data.get("session_id", ""),
                        "data": {"chunk": chk},
                    })
            else:
                session_id = data.get("session_id", "default")
                events.append(migrate_legacy_event(data, session_id))

        return events

    def _read_raw_file(self, path: str) -> SessionInspection:
        if not os.path.exists(path):
            raise FileNotFoundError(f'session file not found: "{path}"')

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if not lines:
            raise ValueError(f'corrupt session file (empty): "{path}"')

        header_dict = json.loads(lines[0].strip())
        if header_dict.get("version", 0) > SESSION_FORMAT_VERSION:
            raise ValueError(
                f'unsupported session version {header_dict.get("version")}; '
                f'current build supports up to {SESSION_FORMAT_VERSION}'
            )

        meta = SessionHeader.from_dict(header_dict)
        events = self._decode_events(lines[1:])
        return SessionInspection(meta=meta, events=events)

    def _check_interrupted_turn(self, session_id: str, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        open_turn: Optional[int] = None
        for event in events:
            etype = event.get("type")
            if etype == "turn/start":
                open_turn = event.get("data", {}).get("turn", 1)
            elif etype == "turn/end":
                open_turn = None

        if open_turn is not None:
            # Crash recovery: orphaned turn detected
            closer_event: Dict[str, Any] = {
                "type": "turn/end",
                "seq": len(events),
                "time": int(time.time() * 1000),
                "session_id": session_id,
                "data": {
                    "turn": open_turn,
                    "reason": {"kind": "interrupted"},
                },
            }
            return [closer_event]
        return []

    async def load(self, session_id: str) -> SessionInspection:
        path = self._find_log_path(session_id)
        if not path:
            raise FileNotFoundError(f'persisted session "{session_id}" not found')

        inspection = self._read_raw_file(path)
        closers = self._check_interrupted_turn(session_id, inspection.events)
        if closers:
            # Durably commit crash repair
            await self.append(session_id, closers)
            inspection.events.extend(closers)

        self._registered_meta[session_id] = inspection.meta
        return inspection

    async def inspect(self, session_id: str) -> SessionInspection:
        path = self._find_log_path(session_id)
        if not path:
            raise FileNotFoundError(f'persisted session "{session_id}" not found')

        inspection = self._read_raw_file(path)
        closers = self._check_interrupted_turn(session_id, inspection.events)
        if closers:
            # Synthetic in-memory view without committing to disk
            events_copy = list(inspection.events) + closers
            return SessionInspection(meta=inspection.meta, events=events_copy)

        return inspection

    async def read_from(self, session_id: str, from_seq: int) -> SessionInspection:
        inspection = await self.inspect(session_id)
        filtered = [e for e in inspection.events if e.get("seq", 0) >= from_seq]
        return SessionInspection(meta=inspection.meta, events=filtered)

    async def list(self) -> List[SessionHeader]:
        headers: List[SessionHeader] = []
        if not os.path.exists(self.root):
            return headers

        for proj in os.listdir(self.root):
            pdir = os.path.join(self.root, proj)
            if os.path.isdir(pdir):
                for sname in os.listdir(pdir):
                    sdir = os.path.join(pdir, sname)
                    lpath = os.path.join(sdir, "session.jsonl")
                    if os.path.isfile(lpath):
                        try:
                            with open(lpath, "r", encoding="utf-8") as f:
                                first_line = f.readline()
                                if first_line:
                                    hdict = json.loads(first_line.strip())
                                    headers.append(SessionHeader.from_dict(hdict))
                        except Exception:
                            continue
        return headers

    async def list_snapshots(self) -> List[SessionPersistenceSnapshot]:
        snapshots: List[SessionPersistenceSnapshot] = []
        for header in await self.list():
            path = self._find_log_path(header.id)
            if path and os.path.exists(path):
                st = os.stat(path)
                rev = f"{st.st_mtime_ns if hasattr(st, 'st_mtime_ns') else st.st_mtime}:{st.st_size}"
                snapshots.append(SessionPersistenceSnapshot(header=header, revision=rev))
        return snapshots

    def on_session_event(self, session: Any, event: Dict[str, Any]) -> None:
        sid = session.id if hasattr(session, "id") else event.get("session_id", "default")
        if sid not in self._pending:
            self._pending[sid] = []
        self._pending[sid].append(event)
        if hasattr(session, "header") and session.header:
            self._registered_meta[sid] = session.header

    async def on_session_flush(self, session: Optional[Any] = None) -> None:
        if session:
            sid = session.id if hasattr(session, "id") else getattr(session, "session_id", "default")
            events = self._pending.pop(sid, [])
            if events:
                await self.append(sid, events)
        else:
            sids = list(self._pending.keys())
            for sid in sids:
                events = self._pending.pop(sid, [])
                if events:
                    await self.append(sid, events)


class JsonlSessionPersistencePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-session-persistence-jsonl`: JSONL durable storage backend.
    """

    id = "session-persistence-jsonl"
    name = "@deepseek-ai/dsh-session-persistence-jsonl"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        root: str = ".dsh/sessions",
        pack_chunks: bool = True,
    ):
        super().__init__(config)
        cfg = self.config or {}
        self.root = str(cfg.get("root", root))
        self.pack_chunks = bool(cfg.get("packChunks", cfg.get("pack_chunks", pack_chunks)))

    def apply(self, ctx: Any) -> None:
        persistence = JsonlSessionPersistence(root=self.root, pack_chunks=self.pack_chunks, ctx=ctx)
        ctx.set_service("session_persistence", persistence)

        # Hook session lifecycle events
        ctx.on("session/event", persistence.on_session_event)
        ctx.on("session/flush", persistence.on_session_flush)
