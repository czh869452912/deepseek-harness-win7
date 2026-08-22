"""
Native path opener helper (`@deepseek-ai/dsh-host-apiproxy/native-path-opener`).
Aligned 1:1 with reference `native-path-opener.ts`.
"""

import os
import subprocess
import sys


def open_native_path(path: str) -> bool:
    """Open target path in OS native file manager or default application."""
    if not path or not os.path.exists(path):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(path)
            return True
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
            return True
        else:
            subprocess.Popen(["xdg-open", path])
            return True
    except Exception:
        return False
