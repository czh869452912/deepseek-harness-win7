"""
Error vocabulary for the storage hub and its backends.
Aligned 1:1 with official `@deepseek-ai/dsh-storage/src/error`.
"""

from typing import Optional


class StorageError(Exception):
    """
    Error thrown by the hub and by backend implementations.
    The `code` is the stable contract consumers may switch on; `message` is diagnostic prose.
    """

    def __init__(self, code: str, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.cause = cause
        self.name = "StorageError"

    def __str__(self) -> str:
        return f"{self.name}[{self.code}]: {self.message}"
