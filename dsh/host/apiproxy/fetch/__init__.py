"""
Fetch Carrier Exports (`@deepseek-ai/dsh-host-apiproxy/fetch`).
Aligned 1:1 with reference `fetch/index.ts`.
"""

from dsh.host.apiproxy.fetch.handler import OFFICIAL_RPC_METHODS, normalize_rpc_method, method_for
from dsh.host.apiproxy.fetch.client import InProcessApiClient

__all__ = [
    "OFFICIAL_RPC_METHODS",
    "normalize_rpc_method",
    "method_for",
    "InProcessApiClient",
]
