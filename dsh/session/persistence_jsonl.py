"""
JSONL durable session-persistence backend for DeepSeek Harness Win7.
Stores SessionHeader on line 1, followed by contiguous SessionEvent lines.
Includes crash recovery (closing interrupted turns), packed chunk rows, and Win32 atomic write protections.
1:1 aligned with official `@deepseek-ai/dsh-session-persistence-jsonl`.
"""

import asyncio
import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from dsh.cordis.plugin import Plugin
from dsh.core.session import SessionHeader, SESSION_FORMAT_VERSION
from dsh.session.persistence import (
    SessionFormatUnsupportedError,
    SessionInspection,
    SessionLocation,
    SessionPersistence,
    SessionPersistenceCorruptionError,
    SessionPersistenceSnapshot,
    session_format_version_refusal,
)
from dsh.session.chunk_rows import decode_storage_record, pack_chunk_runs
from dsh.session.seq_ranges import decode_seq_ranges, encode_seq_ranges


def encode_segment(raw: str) -> str:
    """
    Encode an arbitrary string as a single safe path segment, injectively over all characters.
    Neutralizes ../, absolute paths, NUL, and separators.
    """
    if len(raw) == 0:
        raise ValueError("cannot encode an empty path segment")
    if raw == ".":
        return "~002E"
    if raw == "..":
        return "~002E~002E"
    out = []
    for ch in raw:
        code = ord(ch)
        if ch != "~" and (ch.isalnum() or ch in "._-"):
            out.append(ch)
        else:
            out.append(f"~{code:04X}")
    return "".join(out)


def project_key(cwd: str) -> str:
    """
    Build the readable directory key for a project path.
    """
    if len(cwd) == 0:
        raise ValueError("cannot encode an empty project path")
    readable = []
    separator_run = False
    for ch in cwd:
        if ch in ("/", "\\", ":"):
            if not separator_run:
                readable.append("-")
            separator_run = True
        elif ch != "~" and (ch.isalnum() or ch in "._-"):
            readable.append(ch)
            separator_run = False
        else:
            code = ord(ch)
            readable.append(f"~{code:04X}")
            separator_run = False
    slug = "".join(readable).lstrip("-") or "root"
    return f"--{slug[:251]}--"


def project_dir(root: str, cwd: Optional[str]) -> str:
    if cwd is None:
        return os.path.join(root, "_no-cwd")
    return os.path.join(root, project_key(cwd))


def session_dir(root: str, cwd: Optional[str], session_id: str) -> str:
    return os.path.join(project_dir(root, cwd), encode_segment(session_id))


def log_path(root: str, cwd: Optional[str], session_id: str, compression: str = "none") -> str:
    suffix = ".jsonl"
    return os.path.join(session_dir(root, cwd, session_id), f"session{suffix}")


def to_header_line(header: SessionHeader) -> Dict[str, Any]:
    line: Dict[str, Any] = {
        "type": "session",
        "version": header.version,
        "id": header.id,
        "createdAt": header.created_at,
        "delegationDepth": header.delegation_depth or 0,
    }
    if header.cwd is not None:
        line["cwd"] = header.cwd
    if header.parent_session is not None:
        line["parentSession"] = header.parent_session
    if header.seed_length is not None:
        line["seedLength"] = header.seed_length
    if header.origin is not None:
        line["origin"] = header.origin
    if header.agent_preset is not None:
        line["agentPreset"] = header.agent_preset
    return line


def from_header_line(line: Dict[str, Any]) -> SessionHeader:
    if "sandboxMode" in line or "approvalPolicy" in line:
        raise ValueError("session header uses retired policy baseline fields")
    return SessionHeader.from_dict(line)


def is_header_line(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("type") != "session":
        return False
    if not isinstance(value.get("version"), int) or isinstance(value.get("version"), bool):
        return False
    if not isinstance(value.get("id"), str) or len(value.get("id")) == 0:
        return False
    created_at = value.get("createdAt")
    if not isinstance(created_at, int) or isinstance(created_at, bool) or created_at < 0:
        return False
    delegation_depth = value.get("delegationDepth")
    if delegation_depth is not None:
        if not isinstance(delegation_depth, int) or isinstance(delegation_depth, bool) or delegation_depth < 0:
            return False
    return True


def parse_header_meta(first_line: str) -> Optional[SessionHeader]:
    try:
        parsed = json.loads(first_line.strip())
    except Exception:
        return None
    if not is_header_line(parsed):
        return None
    return from_header_line(parsed)


def win32_atomic_write(target_path: str, lines: List[str]) -> None:
    """
    Windows-safe atomic write using temporary file and retried os.replace.
    """
    tmp_path = f"{target_path}.{int(time.time() * 1000)}.{os.getpid()}.tmp"
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())

    retries = 5
    for attempt in range(retries):
        try:
            os.replace(tmp_path, target_path)
            return
        except OSError:
            if attempt == retries - 1:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                raise
            time.sleep(0.05 * (2 ** attempt))


class SessionLogScanner:
    """
    Incrementally scans complete JSONL event records after a header record.
    """

    def __init__(self, header_bytes: bytes):
        text = header_bytes.decode("utf-8").strip()
        if not text:
            raise ValueError("empty or header-less session log")
        try:
            parsed = json.loads(text)
        except Exception:
            raise ValueError("corrupt session log: header line is not valid JSON")

        if isinstance(parsed, dict):
            ver = parsed.get("version")
            sid = str(parsed.get("id", ""))
            if isinstance(ver, int) and ver != SESSION_FORMAT_VERSION and ver > 1:
                raise SessionFormatUnsupportedError(session_format_version_refusal(sid, ver))

        if not is_header_line(parsed):
            raise ValueError("corrupt session log: first line is not a session header")

        self.meta = from_header_line(parsed)
        self.events: List[Dict[str, Any]] = []
        self.committed_bytes = len(header_bytes)
        self.input_bytes = len(header_bytes)
        self._fragments = bytearray()
        self._event_line = 0
        self._issue: Optional[Exception] = None
        self._finished = False

    def write(self, chunk: bytes) -> None:
        if self._finished:
            raise RuntimeError("cannot write to a finished session log scanner")
        self.input_bytes += len(chunk)
        data = self._fragments + chunk
        self._fragments = bytearray()

        lines = data.split(b"\n")
        self._fragments = bytearray(lines[-1])
        complete_lines = lines[:-1]

        for line_bytes in complete_lines:
            line_str = line_bytes.decode("utf-8").strip()
            if not line_str:
                continue
            self._event_line += 1
            try:
                parsed_rec = json.loads(line_str)
                if isinstance(parsed_rec, dict) and "sourceEventSeqs" in parsed_rec:
                    seq = parsed_rec.get("seq", 0)
                    parsed_rec["sourceEventSeqs"] = decode_seq_ranges(parsed_rec["sourceEventSeqs"], seq)
                decoded = decode_storage_record(parsed_rec)
            except Exception:
                if self._issue is None:
                    self._issue = ValueError(f"corrupt session log: unparsable committed event at line {self._event_line}")
                continue

            if self._issue is not None:
                if any(ev.get("type") == "turn/end" for ev in decoded):
                    raise self._issue
                continue

            row_start = len(self.events)
            for ev in decoded:
                if ev.get("seq") != len(self.events):
                    expected = len(self.events)
                    self.events = self.events[:row_start]
                    self._issue = ValueError(
                        f"corrupt session log: seq gap in committed region at line {self._event_line} (expected {expected}, got {ev.get('seq')})"
                    )
                    if any(candidate.get("type") == "turn/end" for candidate in decoded):
                        raise self._issue
                    break
                self.events.append(ev)

        self.committed_bytes = self.input_bytes - len(self._fragments)

    def finish(self) -> Dict[str, Any]:
        self._finished = True
        return {
            "meta": self.meta,
            "events": self.events,
            "committed_bytes": self.committed_bytes,
        }


def scan_log(buffer: bytes) -> Dict[str, Any]:
    header_end = buffer.find(b"\n")
    if header_end == -1:
        raise ValueError("empty or header-less session log")
    scanner = SessionLogScanner(buffer[: header_end + 1])
    scanner.write(buffer[header_end + 1:])
    return scanner.finish()


class JsonlSessionPersistence(SessionPersistence):
    """
    JSONL durable session-persistence backend.
    """

    supports_raw_artifacts = True

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
        return log_path(self.root, cwd, session_id)

    def _find_log_path(self, session_id: str) -> Optional[str]:
        if not os.path.exists(self.root):
            return None
        enc_id = encode_segment(session_id)
        for proj in os.listdir(self.root):
            pdir = os.path.join(self.root, proj)
            if os.path.isdir(pdir):
                candidate = os.path.join(pdir, enc_id, "session.jsonl")
                if os.path.isfile(candidate):
                    return candidate
                cand2 = os.path.join(pdir, session_id, "session.jsonl")
                if os.path.isfile(cand2):
                    return cand2
        return None

    def locate(self, meta: SessionHeader) -> SessionLocation:
        path = self._log_path(meta.cwd, meta.id)
        return SessionLocation(kind="jsonl", path=path)

    async def read_raw(self, session_id: str) -> Optional[Dict[str, Any]]:
        path = self._find_log_path(session_id)
        if not path or not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        first_line = content.split("\n", 1)[0]
        meta = parse_header_meta(first_line)
        if meta is None:
            raise ValueError("corrupt session log: header line is not valid")
        return {
            "meta": meta,
            "filename": "session.jsonl",
            "content": content,
        }

    async def create(self, meta: SessionHeader) -> None:
        self._registered_meta[meta.id] = meta
        path = self.locate(meta).path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            header_dict = to_header_line(meta)
            header_line = json.dumps(header_dict, ensure_ascii=False)
            win32_atomic_write(path, [header_line])

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
        records = pack_chunk_runs(events) if self.pack_chunks else events
        lines = []
        for rec in records:
            r_copy = dict(rec)
            if "sourceEventSeqs" in r_copy and isinstance(r_copy["sourceEventSeqs"], list):
                r_copy["sourceEventSeqs"] = encode_seq_ranges(r_copy["sourceEventSeqs"])
            lines.append(json.dumps(r_copy, ensure_ascii=False))
        return lines

    def _read_raw_file(self, path: str) -> SessionInspection:
        if not os.path.exists(path):
            raise FileNotFoundError(f'session file not found: "{path}"')

        with open(path, "rb") as f:
            raw_bytes = f.read()

        if not raw_bytes:
            raise ValueError(f'corrupt session file (empty): "{path}"')

        first_newline = raw_bytes.find(b"\n")
        first_line_bytes = raw_bytes[:first_newline] if first_newline != -1 else raw_bytes
        first_line_str = first_line_bytes.decode("utf-8").strip()

        try:
            parsed_header = json.loads(first_line_str)
        except Exception:
            raise ValueError(f'corrupt session log: first line is not a session header in "{path}"')

        if isinstance(parsed_header, dict):
            file_ver = parsed_header.get("version")
            sid = str(parsed_header.get("id", ""))
            if isinstance(file_ver, int) and file_ver > 1:
                raise SessionFormatUnsupportedError(
                    f'session "{sid}" uses log format v{file_ver}, which was written by a newer harness build; upgrade the harness to read this session (raw log: {path})'
                )

        if not is_header_line(parsed_header):
            raise ValueError(f'corrupt session log: first line is not a session header in "{path}"')

        scanned = scan_log(raw_bytes)
        return SessionInspection(meta=scanned["meta"], events=scanned["events"])

    def _check_interrupted_turn(self, session_id: str, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        open_turn: Optional[int] = None
        for event in events:
            etype = event.get("type")
            if etype == "turn/start":
                open_turn = event.get("data", {}).get("turn", 1)
            elif etype == "turn/end":
                open_turn = None

        if open_turn is not None:
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
        if inspection.meta.id != session_id:
            raise ValueError(f'requested id "{session_id}" does not match header id "{inspection.meta.id}"')

        closers = self._check_interrupted_turn(session_id, inspection.events)
        if closers:
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
                                    hdr = parse_header_meta(first_line)
                                    if hdr:
                                        headers.append(hdr)
                        except Exception:
                            continue
        return headers

    async def list_snapshots(self) -> List[SessionPersistenceSnapshot]:
        snapshots: List[SessionPersistenceSnapshot] = []
        for header in await self.list():
            path = self._find_log_path(header.id)
            if path and os.path.exists(path):
                st = os.stat(path)
                mtime = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
                rev = f"{mtime}:{st.st_size}"
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

        ctx.on("session/event", persistence.on_session_event)
        ctx.on("session/flush", persistence.on_session_flush)

