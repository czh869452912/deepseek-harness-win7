"""Stable subagent service error classifications."""


class SubagentError(RuntimeError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code
