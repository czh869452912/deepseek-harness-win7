"""
HarnessError base exception class matching @deepseek-ai/dsh-llm
"""
from typing import Optional


class HarnessError(Exception):
    """
    Base exception class for Harness errors with error message and code.
    """

    def __init__(self, message: str, code: str = "HARNESS_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code
        self.name = self.__class__.__name__

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"
