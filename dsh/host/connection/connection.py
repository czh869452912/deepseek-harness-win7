"""
Host HTTP bridge for browser-client RPC (`@deepseek-ai/dsh-client-connection`).

Historical authentication facade retained for standalone auth contract tests.
Production boot uses CanonicalConnectionPlugin in canonical.py and
HostConnectionService in rpc_host.py: Connection owns /api, while Typert Gateway
registers Remote RPC dispatch and the /api/remote.mux WebSocket. The retired
ApiProxy carrier does not participate in production Web composition.
"""

from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.host.connection.api_trust import assert_trusted_authority, is_trusted_api_request
from dsh.host.connection.browser_auth import BrowserAuth

API_PATH = "/api"
DEFAULT_MAX_REQUEST_BODY_BYTES = 300 * 1024 * 1024
DEFAULT_COOKIE_MAX_AGE_DAYS = 30


class ConnectionService:
    """
    The browser carrier's authentication and trust owner, mounted at
    `ctx.connection`.
    """

    def __init__(self, browser_auth: BrowserAuth, trusted_hosts: Optional[List[str]] = None):
        self.browser_auth = browser_auth
        self.trusted_hosts: List[str] = list(trusted_hosts or [])

    def request_rejection(self, request: Any) -> Optional[int]:
        """Apply the configured Host/Origin fence, then browser authentication."""
        if not is_trusted_api_request(request, self.trusted_hosts):
            return 403
        return None if self.browser_auth.is_authenticated(request) else 401

    def authorize_index(self, request: Any, response: Any) -> bool:
        """Authenticate an index request through the process-token exchange or cookie."""
        return self.browser_auth.authorize_index(request, response)

    def authenticated_url(self, base_url: str) -> str:
        """Add this process's launch token to the clean application URL."""
        return self.browser_auth.authenticated_url(base_url)


class ConnectionPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-client-connection`: browser authentication and the
    `/api` trust fence.
    """

    id = "connection"
    name = "@deepseek-ai/dsh-client-connection"
    inject = ["web_server", "credentials"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        cfg = config or {}
        self.trusted_hosts: List[str] = list(cfg.get("trustedHosts") or [])
        self.cookie_max_age_days = cfg.get("cookieMaxAgeDays", DEFAULT_COOKIE_MAX_AGE_DAYS)
        self.max_request_body_bytes = cfg.get("maxRequestBodyBytes", DEFAULT_MAX_REQUEST_BODY_BYTES)
        self.service: Optional[ConnectionService] = None

    def apply(self, ctx: Any) -> None:
        # Config boundary: a malformed entry fails the load loudly here rather
        # than silently authorizing its hostname prefix at request time.
        for entry in self.trusted_hosts:
            assert_trusted_authority(entry)

        credentials = ctx.get("credentials")
        browser_auth = BrowserAuth.create(ctx.root, credentials, self.cookie_max_age_days)
        self.service = ConnectionService(browser_auth, self.trusted_hosts)
        ctx.set_service("connection", self.service)
        ctx.set_service("connectionService", self.service)
