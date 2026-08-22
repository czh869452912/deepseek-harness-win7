"""
Change-event vocabulary of the domain data form.
Aligned 1:1 with official `@deepseek-ai/dsh-storage-domain/src/events`.
"""

from typing import Any, Dict


class DomainChanged:
    """One durable domain change notification."""

    def __init__(self, domain: str, table: str, key: str, operation: str, value: Any = None):
        self.domain = domain
        self.table = table
        self.key = key
        self.operation = operation  # 'put' or 'deleted'
        self.value = value

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "domain": self.domain,
            "table": self.table,
            "key": self.key,
            "operation": self.operation,
        }
        if self.operation == "put":
            res["value"] = self.value
        return res
