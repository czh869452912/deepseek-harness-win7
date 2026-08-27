"""
Base Directory Picker capability seam (`@deepseek-ai/dsh-host-directory-picker`).
Aligned 1:1 with reference `directory-picker/src/index.ts`.
"""

from typing import Any, Dict


class DirectoryPickerService:
    """
    Abstract directory picker service definition mounted on `ctx.directoryPicker`.
    """

    name = "directoryPicker"

    def __init__(self, ctx: Any):
        self.ctx = ctx
        for key in ("directory_picker", "directoryPicker"):
            try:
                ctx.set_service(key, self)
            except RuntimeError as exc:
                if "has been registered" not in str(exc):
                    raise

    def capability(self) -> Dict[str, Any]:
        raise NotImplementedError
