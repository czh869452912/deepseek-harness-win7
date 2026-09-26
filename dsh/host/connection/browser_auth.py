"""
Browser-session authentication for the Host Connection carrier.

1:1 port of `reference/packages/client/connection/src/browser-auth.ts`.

A process-scoped launch token is minted once per owning context and printed in
the application URL. A GET of the root path carrying exactly that token mints a
signed, authority-bound cookie and redirects to a clean `/`; every later index
request is authorized by that cookie alone. Every other index request receives
the same minimal 401 response.

Python 3.8.10: `hashlib`, `hmac`, `secrets`, `base64`, `json` and
`email.utils.formatdate` replace the Node `node:crypto` primitives; the byte
formats (base64url without padding, hmac-sha256, RFC 5322 GMT date) are
identical because they are the wire contract.
"""

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
from email.utils import formatdate
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlsplit

from dsh.credentials.credentials import credential_key

AUTH_RECORD_KEY = credential_key("client-connection", "browser-session")
DAY_MILLISECONDS = 24 * 60 * 60 * 1000
SECRET_BYTES = 32
TOKEN_QUERY = "token"
COOKIE_PREFIX = "dsh-auth-"
COOKIE_PAYLOAD_VERSION = 1
STORED_SECRET_VERSION = 1
MAX_SAFE_INTEGER = 9007199254740991
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]*$")

_PROCESS_LAUNCH_TOKENS: Dict[int, Any] = {}


def encode_base64url(value: bytes) -> str:
    """Base64url without padding, exactly the Node `encodeBase64Url` form."""
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_base64url(value: str) -> Optional[bytes]:
    """Decode one canonical base64url string; `None` for anything non-canonical."""
    if value is None or not _BASE64URL_PATTERN.match(value) or len(value) % 4 == 1:
        return None
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(value.replace("-", "+").replace("_", "/") + padding)
    except (binascii.Error, ValueError):
        return None
    if encode_base64url(decoded) != value:
        return None
    return decoded


def process_launch_token(owner: Any) -> str:
    """
    The owner-scoped launch token, minted on first use and retained for the
    process (upstream keeps it in a WeakMap keyed by the root context). The
    owning object is retained beside its token so an id cannot be reused by a
    collected object.
    """
    key = id(owner)
    existing = _PROCESS_LAUNCH_TOKENS.get(key)
    if existing is not None and existing[0] is owner:
        return existing[1]
    created = encode_base64url(secrets.token_bytes(SECRET_BYTES))
    _PROCESS_LAUNCH_TOKENS[key] = (owner, created)
    return created


def header(headers: Any, name: str) -> Optional[str]:
    """Read one request header, lower-cased like the node:http carrier."""
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        return None
    return value if isinstance(value, str) else None


def parse_host(value: str) -> Optional[tuple]:
    """
    Split one authority/URL into `(hostname, port)` with the WHATWG hostname
    rules Python's `http.client`/`urlsplit` share (lower-cased, brackets
    stripped from IPv6 literals). `None` when unparsable.
    """
    if not value:
        return None
    text = value if "//" in value else f"http://{value}"
    try:
        parsed = urlsplit(text)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not hostname:
        return None
    return hostname, port


def whatwg_host(value: str) -> Optional[str]:
    """
    WHATWG `URL.host` for one authority or absolute URL: lower-cased hostname,
    default port stripped, IPv6 literal kept bracketed. `None` when unparsable.
    """
    if not value:
        return None
    text = value if "//" in value else f"http://{value}"
    try:
        parsed = urlsplit(text)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if not hostname:
        return None
    display = f"[{hostname}]" if (parsed.netloc.startswith("[") or "]" in parsed.netloc) else hostname
    default_port = 80 if parsed.scheme.lower() in ("http", "") else 443 if parsed.scheme.lower() == "https" else None
    if port is None or port == default_port:
        return display
    return f"{display}:{port}"


def canonical_authority(authority: str) -> Optional[str]:
    """WHATWG `URL.host` for one bare authority string."""
    return whatwg_host(authority)


def request_authority(headers: Any) -> Optional[str]:
    """Canonical request authority used as the cookie name and signed audience."""
    return canonical_authority(header(headers, "host"))


def canonical_secret(value: Any) -> Optional[bytes]:
    if not isinstance(value, str):
        return None
    decoded = decode_base64url(value)
    if decoded is None or len(decoded) != SECRET_BYTES:
        return None
    return decoded


def stored_secret(record: Optional[Dict[str, Any]]) -> Optional[bytes]:
    if record is None:
        return None
    if record.get("kind") != "grant" or not isinstance(record.get("payload"), dict):
        raise ValueError("client-connection: browser-session credential record has an unsupported format")
    if record["payload"].get("version") != STORED_SECRET_VERSION:
        raise ValueError("client-connection: browser-session credential record has an unsupported format")
    secret = canonical_secret(record["payload"].get("secret"))
    if secret is None:
        raise ValueError("client-connection: browser-session credential record has an invalid secret")
    return secret


def token_matches(actual: str, expected: str) -> bool:
    actual_bytes = actual.encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    if len(actual_bytes) != len(expected_bytes):
        return False
    return hmac.compare_digest(actual_bytes, expected_bytes)


def cookie_name(authority: str) -> str:
    return COOKIE_PREFIX + encode_base64url(hashlib.sha256(authority.encode("utf-8")).digest())


def cookie_value(header_value: str, name: str) -> Optional[str]:
    """Read the exact generated cookie without implementing general Cookie decoding."""
    for segment in header_value.split(";"):
        at = segment.find("=")
        if at == -1 or segment[:at].strip() != name:
            continue
        return segment[at + 1:].strip()
    return None


def session_cookie(name: str, value: str, expires_at: int, max_age_seconds: int) -> str:
    """Serialize the fixed browser-session attributes; generated names and values are cookie-safe base64url."""
    expires = formatdate(expires_at / 1000.0, usegmt=True)
    return (
        f"{name}={value}; Max-Age={max_age_seconds}; Path=/; "
        f"Expires={expires}; HttpOnly; SameSite=Strict"
    )


def signature(secret: bytes, body: str) -> bytes:
    return hmac.new(secret, body.encode("utf-8"), hashlib.sha256).digest()


def encode_cookie(payload: Dict[str, Any], secret: bytes) -> str:
    body = encode_base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"v1.{body}.{encode_base64url(signature(secret, body))}"


def is_safe_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and abs(value) <= MAX_SAFE_INTEGER


def decode_cookie(value: str, secret: bytes) -> Optional[Dict[str, Any]]:
    parts = value.split(".")
    if len(parts) != 3:
        return None
    version, body, encoded_signature = parts
    if version != "v1":
        return None
    actual_signature = decode_base64url(encoded_signature)
    if actual_signature is None:
        return None
    expected_signature = signature(secret, body)
    if len(actual_signature) != len(expected_signature):
        return None
    if not hmac.compare_digest(actual_signature, expected_signature):
        return None
    try:
        body_bytes = decode_base64url(body)
        if body_bytes is None:
            return None
        decoded = json.loads(body_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if (
        not isinstance(decoded, dict)
        or decoded.get("version") != COOKIE_PAYLOAD_VERSION
        or not isinstance(decoded.get("authority"), str)
        or not is_safe_integer(decoded.get("issuedAt"))
        or not is_safe_integer(decoded.get("expiresAt"))
    ):
        return None
    return decoded


def initialize_secret(credentials: Any) -> bytes:
    """Create the durable signing secret when this Harness home has none."""
    generated = {
        "version": STORED_SECRET_VERSION,
        "secret": encode_base64url(secrets.token_bytes(SECRET_BYTES)),
    }

    def mutate(current: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if current is not None:
            stored_secret(current)
            return None
        return {"kind": "grant", "payload": generated}

    record = credentials.modify_record(AUTH_RECORD_KEY, mutate)
    secret = stored_secret(record)
    if secret is None:
        raise ValueError("client-connection: browser-session credential record was not created")
    return secret


class BrowserAuth:
    """
    Process launch-token exchange and persistent signed-cookie verification.

    Connection loads the credential provider's signing secret during activation
    and retains it for synchronous request authentication.
    """

    def __init__(self, process_owner: Any, secret: bytes, max_age_days: int):
        self.launch_token = process_launch_token(process_owner)
        self.secret = secret
        self.max_age_milliseconds = max_age_days * DAY_MILLISECONDS
        if (
            abs(self.max_age_milliseconds) > MAX_SAFE_INTEGER
            or abs(int(time.time() * 1000) + self.max_age_milliseconds) > MAX_SAFE_INTEGER
        ):
            raise ValueError("client-connection: cookieMaxAgeDays exceeds the safe timestamp range")

    @classmethod
    def create(cls, process_owner: Any, credentials: Any, max_age_days: int) -> "BrowserAuth":
        """
        Initialize browser authentication and create its durable signing secret
        when this Harness home has none.
        """
        return cls(process_owner, initialize_secret(credentials), max_age_days)

    def authenticated_url(self, base_url: str) -> str:
        """Add this process's launch token to the ordinary application root URL."""
        parsed = urlsplit(base_url)
        scheme = parsed.scheme or "http"
        return f"{scheme}://{parsed.netloc}/?{TOKEN_QUERY}={self.launch_token}"

    def is_authenticated(self, request: Any) -> bool:
        """Verify the authority-bound browser cookie on a Host request."""
        headers = request.get("headers") if isinstance(request, dict) else None
        authority = request_authority(headers)
        raw_cookie = header(headers, "cookie")
        if authority is None or raw_cookie is None:
            return False
        value = cookie_value(raw_cookie, cookie_name(authority))
        if value is None:
            return False
        payload = decode_cookie(value, self.secret)
        if payload is None or payload.get("authority") != authority:
            return False
        issued_at = payload["issuedAt"]
        expires_at = payload["expiresAt"]
        now = int(time.time() * 1000)
        return (
            issued_at <= now
            and expires_at > now
            and expires_at > issued_at
            and expires_at - issued_at <= self.max_age_milliseconds
        )

    def authorize_index(self, request: Any, response: Any) -> bool:
        """
        Authenticate an index request. A valid root query token mints the cookie
        and redirects to clean `/`; a valid cookie lets the caller serve the
        index; every other request receives the same minimal 401 response.

        Returns true only when the caller may serve index.html.
        """
        raw_url = self._raw_url(request)
        parsed = urlsplit(raw_url)
        pathname = parsed.path or "/"
        tokens = parse_qs(parsed.query, keep_blank_values=True).get(TOKEN_QUERY, [])
        method = request.get("method", "GET")

        if len(tokens) > 0:
            headers = request.get("headers") or {}
            authority = request_authority(headers)
            if (
                method == "GET"
                and pathname == "/"
                and len(tokens) == 1
                and authority is not None
                and token_matches(tokens[0], self.launch_token)
            ):
                issued_at = int(time.time() * 1000)
                expires_at = issued_at + self.max_age_milliseconds
                value = encode_cookie(
                    {
                        "version": COOKIE_PAYLOAD_VERSION,
                        "authority": authority,
                        "issuedAt": issued_at,
                        "expiresAt": expires_at,
                    },
                    self.secret,
                )
                response.write_status(303)
                response.write_header("cache-control", "no-store")
                response.write_header("location", "/")
                response.write_header("referrer-policy", "no-referrer")
                response.write_header(
                    "set-cookie",
                    session_cookie(
                        cookie_name(authority),
                        value,
                        expires_at,
                        int(self.max_age_milliseconds / 1000),
                    ),
                )
                return False
            if method == "GET" and pathname == "/" and self.is_authenticated(request):
                response.write_status(303)
                response.write_header("cache-control", "no-store")
                response.write_header("location", "/")
                response.write_header("referrer-policy", "no-referrer")
                return False
            self.write_unauthorized(request, response)
            return False

        if self.is_authenticated(request):
            return True
        self.write_unauthorized(request, response)
        return False

    @staticmethod
    def _raw_url(request: Any) -> str:
        if isinstance(request, dict):
            raw = request.get("raw_url")
            if isinstance(raw, str) and raw:
                return raw
            path = request.get("path") or "/"
            query = request.get("query") or ""
            return f"{path}?{query}" if query else path
        return "/"

    @staticmethod
    def write_unauthorized(request: Any, response: Any) -> None:
        response.write_status(401)
        response.write_header("cache-control", "no-store")
        response.write_header("content-type", "text/plain; charset=utf-8")
        if request.get("method") != "HEAD":
            response.write_body(b"dsh web authentication required; reopen the URL printed by dsh web.\n")
