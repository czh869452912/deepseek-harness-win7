"""
Spill Storage Capability (`ctx.spillStore`) and `@deepseek-ai/dsh-spill-local` implementation.
"""

import hashlib
import os
import re
import tempfile
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service


def encode_segment(raw: str) -> str:
    if len(raw) == 0:
        return "~"
    if raw == ".":
        return "~002E"
    if raw == "..":
        return "~002E~002E"
    out = []
    for ch in raw:
        code = ord(ch)
        if ch != "~" and re.match(r"^[A-Za-z0-9._-]$", ch):
            out.append(ch)
        else:
            out.append(f"~{code:04X}")
    return "".join(out)


def session_dir(root: str, session_id: str) -> str:
    h = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]
    return os.path.join(root, f"session-{h}")


class SpillStore(Service):
    """
    Local filesystem spill store (`ctx.spillStore`).
    """

    def __init__(self, ctx: Optional[Any] = None, root: Optional[str] = None):
        if ctx is not None:
            super().__init__(ctx, "spillStore")
            ctx.set_service("spill_store", self)
            ctx.set_service("spillStore", self)
        else:
            self.ctx = None
        self._root = root

    @property
    def root(self) -> str:
        if self._root is None:
            self._root = tempfile.mkdtemp(prefix="dsh-spill-")
        return self._root

    def save_text(
        self,
        input_data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        suggested_name: Optional[str] = None,
        content: Optional[str] = None,
        owner: Optional[Dict[str, Any]] = None,
        source: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        data = input_data or {}
        sess_id = session_id or data.get("session_id") or (data.get("owner", {}).get("sessionId") if isinstance(data.get("owner"), dict) else "default")
        if owner and isinstance(owner, dict) and "sessionId" in owner:
            sess_id = owner["sessionId"]
        
        name_hint = suggested_name or data.get("suggestedName") or "spill.txt"
        text = content if content is not None else data.get("content", "")

        s_dir = session_dir(self.root, sess_id)
        os.makedirs(s_dir, exist_ok=True, mode=0o700)

        safe_name = encode_segment(name_hint)
        rnd_hex = os.urandom(3).hex()
        filename = f"{rnd_hex}-{safe_name}"
        file_path = os.path.join(s_dir, filename)

        text_bytes = text.encode("utf-8")
        with open(file_path, "wb") as f:
            f.write(text_bytes)

        locator = file_path
        retrieval_hint = "Read with shell cat or file tool"

        return {
            "locator": locator,
            "bytes": len(text_bytes),
            "retrievalHint": retrieval_hint,
            "path": file_path,
        }

    saveText = save_text

    def write_spill(self, data: str, session_id: str = "default") -> str:
        ref = self.save_text(session_id=session_id, suggested_name="spill.txt", content=data)
        return ref["locator"]

    def read_spill(self, file_path: str) -> Optional[str]:
        if not os.path.exists(file_path):
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()


class SpillStorePlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-spill-local`: Saves oversized tool outputs to disk.
    """

    id = "spill-local"
    name = "@deepseek-ai/dsh-spill-local"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        root = cfg.get("root")
        self.root = root

    def apply(self, ctx: Any) -> None:
        store = SpillStore(ctx=ctx, root=self.root)
        ctx.set_service("spillStore", store)
        ctx.set_service("spill_store", store)
