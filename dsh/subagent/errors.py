"""Stable subagent service error classifications."""
from dsh.llm.error import HarnessError


class SubagentError(HarnessError, RuntimeError):
    def __init__(self, message, code):
        super().__init__(message, code)

    def __str__(self):
        return self.message
