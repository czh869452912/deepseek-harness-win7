"""
`@deepseek-ai/dsh-client-connection` — host HTTP bridge for browser-client RPC.

Python 3.8.10 / Windows 7 port of the pinned `reference/packages/client/connection`
host half:
  * `browser-auth.ts`      -> :mod:`dsh.host.connection.browser_auth`
  * `api-request-trust.ts` -> :mod:`dsh.host.connection.api_trust`
  * `index.ts` (`apply`)   -> :mod:`dsh.host.connection.connection`
"""

from dsh.host.connection.browser_auth import BrowserAuth
from dsh.host.connection.connection import (
    ConnectionPlugin,
    ConnectionService,
    API_PATH,
    DEFAULT_MAX_REQUEST_BODY_BYTES,
)

__all__ = [
    "BrowserAuth",
    "ConnectionPlugin",
    "ConnectionService",
    "API_PATH",
    "DEFAULT_MAX_REQUEST_BODY_BYTES",
]
