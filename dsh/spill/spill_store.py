import hashlib
import os
from typing import Any, Dict, Optional
from dsh.cordis.plugin import Plugin


class SpillStore:
    def __init__(self, root: Optional[str] = None):
        self.root = root or os.path.expanduser("~/.dsh/spills")
        os.makedirs(self.root, exist_ok=True)

    def write_spill(self, data: str) -> str:
        data_bytes = data.encode("utf-8")
        h = hashlib.sha256(data_bytes).hexdigest()[:16]
        file_path = os.path.join(self.root, f"{h}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(data)
        return file_path

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

    def apply(self, ctx: Any) -> None:
        ctx.set_service("spillStore", SpillStore())
