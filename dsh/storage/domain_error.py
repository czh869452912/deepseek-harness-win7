"""
Error vocabulary of the domain data form.
Aligned 1:1 with official `@deepseek-ai/dsh-storage-domain/src/error`.
"""

from typing import Any, Dict, Optional


class DomainError(Exception):
    """Error thrown by the domain layer."""

    def __init__(
        self,
        code: str,
        message: str,
        detail: Optional[Dict[str, str]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.cause = cause
        self.name = "DomainError"

    def __str__(self) -> str:
        return f"{self.name}[{self.code}]: {self.message}"
