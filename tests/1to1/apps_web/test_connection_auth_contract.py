"""
1:1 mapping of the `@deepseek-ai/dsh-client-connection` host-half official cases
(`reference/packages/client/connection/tests/api-request-trust.host.spec.ts`,
`browser-auth.host.spec.ts`, `loopback-hostname.client.spec.ts`) behind the
authenticated served `apps/web` payload.

Ported cases:

  - ``holds markerless requests to the same Host fence``
  - ``accepts loopback Hosts in every spelling, with and without ports``
  - ``refuses a rebound Host``
  - ``accepts a declared public authority``
  - ``matches Host, Origin, and trusted entries through WHATWG normalization``
  - ``refuses cross-origin browser markers even on a loopback Host``
  - ``accepts a same-origin browser request, with or without an Origin header``
  - ``assertTrustedAuthority accepts bare authorities and throws on anything more``
  - ``never lets stray whitespace broaden an exact-port entry to every port``
  - ``refuses malformed or untrusted authorities on browser requests``
  - ``accepts localhost, IPv6 loopback, and the whole IPv4 127/8 block``
  - ``refuses malformed and non-loopback hostnames``
  - ``mints one process token and a persistent authority-bound cookie``
  - ``accepts the cookie for index serving and gives every unauthenticated
    request one response``
  - ``rejects tampering, expiry, future issuance, and a longer lifetime than
    configured``
  - ``loads one secret per activation and replaces it after deletion on the next
    activation``
  - ``fails loud on an invalid owner record instead of replacing it``

Not ported here (recorded gaps): the Fetch-`Headers` arm of the trust fence (the
port's carrier hands handlers a plain mapping), and the RPC bridge cases of
`node-half.host.spec.ts` (this port's `/api` route owner is the merged
apiproxy plugin; its fence application is covered by
`test_served_http_fence.py`).
"""

import asyncio
import json
import os
import time

import pytest

from dsh.cordis.context import Context
from dsh.credentials.credentials_local import CredentialsLocalPlugin
from dsh.host.connection import browser_auth as ba
from dsh.host.connection.api_trust import assert_trusted_authority, is_trusted_api_request
from dsh.host.connection.browser_auth import BrowserAuth, cookie_name
from dsh.host.connection.connection import ConnectionPlugin, ConnectionService


def request(headers):
    return {"headers": headers}


def test_holds_markerless_requests_to_the_same_host_fence():
    # Over plain HTTP a browser attaches neither Origin nor Fetch-Metadata to
    # reads, so a rebound-origin GET is markerless: no marker shortcut may exist.
    assert is_trusted_api_request(request({"host": "127.0.0.1:3080"}), []) is True
    assert is_trusted_api_request(request({"host": "192.168.1.5:3080"}), ["192.168.1.5"]) is True
    assert is_trusted_api_request(request({"host": "192.168.1.5:3080"}), []) is False
    assert is_trusted_api_request(request({"host": "harness.example"}), []) is False
    assert is_trusted_api_request(request({}), []) is False


def test_accepts_loopback_hosts_in_every_spelling_with_and_without_ports():
    for host in [
        "localhost",
        "localhost:3080",
        "127.0.0.1",
        "127.0.0.1:3080",
        "127.8.9.10:80",
        "[::1]",
        "[::1]:3080",
        "LOCALHOST:3080",
    ]:
        assert is_trusted_api_request(request({"host": host, "origin": "http://%s" % host}), []) is True, host


def test_refuses_a_rebound_host():
    assert (
        is_trusted_api_request(
            request(
                {
                    "host": "evil.example:3080",
                    "origin": "http://evil.example:3080",
                    "sec-fetch-site": "same-origin",
                }
            ),
            [],
        )
        is False
    )


def test_accepts_a_declared_public_authority():
    headers = {"host": "harness.internal:3080", "origin": "http://harness.internal:3080"}
    assert is_trusted_api_request(request(headers), ["harness.internal:3080"]) is True
    assert is_trusted_api_request(request(headers), ["harness.internal"]) is True
    assert is_trusted_api_request(request(headers), ["harness.internal:9999"]) is False
    assert is_trusted_api_request(request(headers), []) is False


def test_matches_host_origin_and_trusted_entries_through_whatwg_normalization():
    assert (
        is_trusted_api_request(
            request({"host": "Harness.INTERNAL:3080", "origin": "http://harness.internal:3080"}),
            ["harness.internal:3080"],
        )
        is True
    )
    assert (
        is_trusted_api_request(
            request({"host": "harness.internal", "origin": "http://harness.internal"}),
            ["HARNESS.internal:80"],
        )
        is True
    )
    # An unparsable entry never matches; it must not poison the rest of the list.
    assert (
        is_trusted_api_request(
            request({"host": "harness.internal", "origin": "http://harness.internal"}),
            ["bad entry", "harness.internal"],
        )
        is True
    )
    assert (
        is_trusted_api_request(
            request({"host": "harness.internal", "origin": "http://harness.internal"}),
            ["bad entry"],
        )
        is False
    )


def test_refuses_cross_origin_browser_markers_even_on_a_loopback_host():
    assert is_trusted_api_request(request({"host": "127.0.0.1:3080", "origin": "http://evil.example"}), []) is False
    assert is_trusted_api_request(request({"host": "127.0.0.1:3080", "sec-fetch-site": "cross-site"}), []) is False
    assert is_trusted_api_request(request({"host": "127.0.0.1:3080", "origin": "null"}), []) is False


def test_accepts_a_same_origin_browser_request_with_or_without_an_origin_header():
    assert (
        is_trusted_api_request(
            request({"host": "localhost:3080", "origin": "http://localhost:3080", "sec-fetch-site": "same-origin"}),
            [],
        )
        is True
    )
    assert (
        is_trusted_api_request(request({"host": "localhost:3080", "sec-fetch-site": "same-origin"}), []) is True
    )


def test_assert_trusted_authority_accepts_bare_authorities_and_throws_on_anything_more():
    for entry in ["harness.internal", "harness.internal:3080", "HARNESS.internal:80", "10.0.0.9", "[::1]:3080"]:
        assert_trusted_authority(entry)
    # Parsing would quietly read a hostname out of each of these; the config
    # boundary must refuse them instead of authorizing the prefix.
    for entry in [
        "harness.internal/path",
        "harness.internal/",
        "user@harness.internal",
        "harness.internal?x",
        "harness.internal#f",
        "harness.internal\\path",
        "bad entry",
        "",
    ]:
        with pytest.raises(ValueError, match=r"not a bare host\[:port\] authority"):
            assert_trusted_authority(entry)
    # Trimming would silently strip these; the entry must fail instead.
    for entry in ["harness.internal:3080 ", " harness.internal", "harness.internal:30\t80"]:
        with pytest.raises(ValueError, match=r"not a bare host\[:port\] authority"):
            assert_trusted_authority(entry)
    # A dangling colon or zero-padded port would broaden an intended exact-port
    # grant to every port, and non-canonical host spellings would not read back
    # as written.
    for entry in ["harness.internal:", "[::1]:", "harness.internal:0080", "0x7f.0.0.1", "[0:0:0:0:0:0:0:1]"]:
        with pytest.raises(ValueError, match=r"not a bare host\[:port\] authority"):
            assert_trusted_authority(entry)


def test_never_lets_stray_whitespace_broaden_an_exact_port_entry_to_every_port():
    trusted = ["harness.internal:3080 "]
    assert (
        is_trusted_api_request(
            request({"host": "harness.internal:9999", "origin": "http://harness.internal:9999"}), trusted
        )
        is False
    )
    assert (
        is_trusted_api_request(
            request({"host": "harness.internal:3080", "origin": "http://harness.internal:3080"}), trusted
        )
        is True
    )


def test_refuses_malformed_or_untrusted_authorities_on_browser_requests():
    markers = {"sec-fetch-site": "same-origin"}
    assert is_trusted_api_request(request(dict(markers)), []) is False
    assert is_trusted_api_request(request(dict(markers, host="")), []) is False
    assert is_trusted_api_request(request(dict(markers, host="bad host")), []) is False
    assert is_trusted_api_request(request(dict(markers, host="127.0.0.999")), []) is False
    assert is_trusted_api_request(request(dict(markers, host="128.0.0.1")), []) is False


def test_accepts_localhost_ipv6_loopback_and_the_whole_ipv4_127_8_block():
    from dsh.host.connection.api_trust import is_loopback_hostname

    for hostname in ["localhost", "[::1]", "::1", "127.0.0.1", "127.0.0.2", "127.255.255.255", "127.8.9.10"]:
        assert is_loopback_hostname(hostname) is True, hostname


def test_refuses_malformed_and_non_loopback_hostnames():
    from dsh.host.connection.api_trust import is_loopback_hostname

    for hostname in ["", "localhost.example", "127.0.0.256", "127.0.0", "128.0.0.1", "::2", "example.test"]:
        assert is_loopback_hostname(hostname) is False, hostname


class RecordingResponse:
    """Minimal response writer capturing the authorization exchange."""

    def __init__(self):
        self.status = None
        self.headers = {}
        self.body = bytearray()

    def write_status(self, status):
        self.status = status

    def write_header(self, key, value):
        self.headers[key] = value

    def write_body(self, data):
        self.body.extend(data)


def make_auth(credentials, owner=None, max_age_days=30):
    return BrowserAuth.create(owner if owner is not None else object(), credentials, max_age_days)


class _Credentials:
    """In-memory stand-in for the credential provider's record store."""

    def __init__(self, path):
        self.path = path
        self.records = {}

    def modify_record(self, key, mutate):
        current = self.records.get(key)
        result = mutate(current)
        if result is None:
            return current
        self.records[key] = result
        return result


def index_request(authority="127.0.0.1", raw_url="/", method="GET", cookie=None):
    headers = {"host": authority}
    if cookie is not None:
        headers["cookie"] = cookie
    return {
        "method": method,
        "path": raw_url.split("?")[0],
        "query": raw_url.split("?", 1)[1] if "?" in raw_url else "",
        "raw_url": raw_url,
        "headers": headers,
    }


def test_mints_one_process_token_and_a_persistent_authority_bound_cookie(tmp_path):
    owner = object()
    credentials = _Credentials(str(tmp_path / ".credentials.yaml"))
    auth = make_auth(credentials, owner=owner)
    second = make_auth(credentials, owner=owner)
    # One token per owning context, retained across activations.
    assert auth.launch_token == second.launch_token
    assert auth.launch_token != ""

    url = auth.authenticated_url("http://127.0.0.1:8123/path?x=1#y")
    assert url == "http://127.0.0.1:8123/?token=%s" % auth.launch_token

    response = RecordingResponse()
    assert auth.authorize_index(index_request(raw_url="/?token=" + auth.launch_token), response) is False
    assert response.status == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(cookie_name("127.0.0.1") + "=")
    assert "Max-Age=2592000" in cookie
    assert "Path=/" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie

    # The cookie is authority-bound and signed by the durable secret.
    value = cookie.split(";", 1)[0].split("=", 1)[1]
    assert value.startswith("v1.")
    assert auth.is_authenticated(index_request(cookie=cookie)) is True

    # A later activation loads the same durable secret from the credential store.
    reloaded = make_auth(credentials, owner=owner)
    assert reloaded.secret == auth.secret
    assert reloaded.is_authenticated(index_request(cookie=cookie)) is True
    assert ba.AUTH_RECORD_KEY in credentials.records


def issue_cookie(auth, authority="127.0.0.1", issued_at=None, expires_at=None):
    """Build one signed cookie payload exactly as the exchange does."""
    now = int(time.time() * 1000)
    payload = {
        "version": ba.COOKIE_PAYLOAD_VERSION,
        "authority": authority,
        "issuedAt": now if issued_at is None else issued_at,
        "expiresAt": (now + ba.DAY_MILLISECONDS) if expires_at is None else expires_at,
    }
    return ba.encode_cookie(payload, auth.secret)


def test_accepts_the_cookie_for_index_serving_and_gives_every_unauthenticated_request_one_response(tmp_path):
    auth = make_auth(_Credentials(str(tmp_path / ".credentials.yaml")))
    response = RecordingResponse()
    auth.authorize_index(index_request(raw_url="/?token=" + auth.launch_token), response)
    cookie = response.headers["set-cookie"]

    assert auth.authorize_index(index_request(cookie=cookie), RecordingResponse()) is True

    for facts in (index_request(), index_request(raw_url="/?token=wrong"), index_request(raw_url="/other")):
        denied = RecordingResponse()
        assert auth.authorize_index(facts, denied) is False
        assert denied.status == 401
        assert denied.headers["content-type"] == "text/plain; charset=utf-8"
        assert bytes(denied.body) == b"dsh web authentication required; reopen the URL printed by dsh web.\n"

    head = RecordingResponse()
    assert auth.authorize_index(index_request(method="HEAD"), head) is False
    assert head.status == 401
    assert bytes(head.body) == b""


def test_rejects_tampering_expiry_future_issuance_and_a_longer_lifetime_than_configured(tmp_path):
    auth = make_auth(_Credentials(str(tmp_path / ".credentials.yaml")), max_age_days=1)
    response = RecordingResponse()
    auth.authorize_index(index_request(raw_url="/?token=" + auth.launch_token), response)
    cookie = response.headers["set-cookie"]
    name = cookie_name("127.0.0.1")
    value = cookie.split(";", 1)[0].split("=", 1)[1]
    now = int(time.time() * 1000)

    assert auth.is_authenticated(index_request(cookie="%s=%s" % (name, value + "x"))) is False

    # A value signed by another secret never verifies.
    other = make_auth(_Credentials(str(tmp_path / "other.yaml")))
    assert other.secret != auth.secret
    other_cookie = ba.encode_cookie(
        {"version": ba.COOKIE_PAYLOAD_VERSION, "authority": "127.0.0.1", "issuedAt": now, "expiresAt": now + 3600000},
        other.secret,
    )
    assert auth.is_authenticated(index_request(cookie="%s=%s" % (name, other_cookie))) is False

    # Expiry, future issuance, and a lifetime beyond the configured maximum.
    expired = issue_cookie(auth, issued_at=now - 10 * ba.DAY_MILLISECONDS, expires_at=now - 1000)
    assert auth.is_authenticated(index_request(cookie="%s=%s" % (name, expired))) is False
    future = issue_cookie(auth, issued_at=now + 60000, expires_at=now + 120000)
    assert auth.is_authenticated(index_request(cookie="%s=%s" % (name, future))) is False
    long_lived = issue_cookie(auth, issued_at=now, expires_at=now + 3 * ba.DAY_MILLISECONDS)
    assert auth.is_authenticated(index_request(cookie="%s=%s" % (name, long_lived))) is False

    # A live cookie still verifies, and it is authority-bound.
    assert auth.is_authenticated(index_request(cookie=cookie)) is True
    assert auth.is_authenticated(index_request(authority="localhost", cookie=cookie)) is False


def test_loads_one_secret_per_activation_and_replaces_it_after_deletion_on_the_next_activation(tmp_path):
    credentials = _Credentials(str(tmp_path / ".credentials.yaml"))
    first = BrowserAuth.create(object(), credentials, 30)
    second = BrowserAuth.create(object(), credentials, 30)
    assert first.secret == second.secret
    del credentials.records[ba.AUTH_RECORD_KEY]
    third = BrowserAuth.create(object(), credentials, 30)
    assert third.secret != first.secret


def test_fails_loud_on_an_invalid_owner_record_instead_of_replacing_it(tmp_path):
    credentials = _Credentials(str(tmp_path / ".credentials.yaml"))
    credentials.records[ba.AUTH_RECORD_KEY] = {"kind": "grant", "payload": {"version": 1, "secret": "short"}}
    with pytest.raises(ValueError, match="invalid secret"):
        BrowserAuth.create(object(), credentials, 30)
    credentials.records[ba.AUTH_RECORD_KEY] = {"kind": "api-key", "payload": {}}
    with pytest.raises(ValueError, match="unsupported format"):
        BrowserAuth.create(object(), credentials, 30)


def test_connection_service_applies_fence_then_authentication(tmp_path):
    auth = make_auth(_Credentials(str(tmp_path / ".credentials.yaml")))
    service = ConnectionService(auth, ["harness.internal:3080"])
    assert service.request_rejection(request({"host": "evil.example:3080"})) == 403
    assert service.request_rejection(request({"host": "127.0.0.1:3080"})) == 401

    # A browser session is bound to the authority it was minted for: the same
    # policy (and the same secret) carries across declared authorities, but the
    # cookie must be minted for the authority the request arrives on.
    loopback_cookie = _minted_cookie(service, "127.0.0.1:3080")
    assert service.request_rejection(request({"host": "127.0.0.1:3080", "cookie": loopback_cookie})) is None
    assert service.request_rejection(request({"host": "harness.internal:3080", "cookie": loopback_cookie})) == 401
    declared_cookie = _minted_cookie(service, "harness.internal:3080")
    assert service.request_rejection(request({"host": "harness.internal:3080", "cookie": declared_cookie})) is None


def _minted_cookie(service, authority):
    response = RecordingResponse()
    service.authorize_index(index_request(authority=authority, raw_url="/?token=" + service.browser_auth.launch_token), response)
    assert response.status == 303, authority
    return response.headers["set-cookie"].split(";", 1)[0]


@pytest.mark.asyncio
async def test_plugin_fails_the_load_on_a_trusted_hosts_entry_that_is_not_a_bare_authority(tmp_path):
    ctx = Context()
    ctx.set_service("web_server", object())
    await ctx.plugin(CredentialsLocalPlugin, config={"path": str(tmp_path / ".credentials.yaml"), "watch": False})
    plugin = ConnectionPlugin(config={"trustedHosts": ["harness.internal/path"]})
    with pytest.raises(ValueError, match=r"not a bare host\[:port\] authority"):
        plugin.apply(ctx)


@pytest.mark.asyncio
async def test_shipped_api_route_refuses_untrusted_and_unauthenticated_requests_before_the_bridge(tmp_path):
    """
    The merged `/api` owner (this port's apiproxy) applies the connection fence
    and authentication before dispatch, exactly as upstream's Connection row
    does for the shared channel.
    """
    from dsh.harness import build_harness

    ctx = await build_harness(mode="standard", enable_web=True, web_port=0)
    try:
        server = ctx.get("web_server")
        route = server.match("/api/pluginInventory.list")
        assert route is not None and route.path == "/api"

        async def call(headers, cookie=None):
            response = RecordingResponse()

            async def finish():
                pass

            response.finish = finish
            request_facts = {
                "method": "POST",
                "path": "/api/pluginInventory.list",
                "query": "",
                "headers": dict(headers),
                "body": json.dumps(
                    {"type": "client-request", "rpcId": "r1", "method": "pluginInventory.list", "payload": {}}
                ).encode("utf-8"),
            }
            if cookie is not None:
                request_facts["headers"]["cookie"] = cookie
            await route.handler(request_facts, response)
            return response

        rejected = await call({"host": "evil.example:3080"})
        assert rejected.status == 403
        assert bytes(rejected.body) == b"forbidden"

        unauthenticated = await call({"host": "127.0.0.1:3080"})
        assert unauthenticated.status == 401
        assert bytes(unauthenticated.body) == b"unauthorized"

        # A browser session minted by the index exchange passes the fence.
        exchange = RecordingResponse()
        ctx.get("connection").authorize_index(
            {
                "method": "GET",
                "path": "/",
                "query": "token=" + ctx.get("connection").browser_auth.launch_token,
                "raw_url": "/?token=" + ctx.get("connection").browser_auth.launch_token,
                "headers": {"host": "127.0.0.1:3080"},
            },
            exchange,
        )
        cookie = exchange.headers["set-cookie"].split(";", 1)[0]
        dispatched = await call({"host": "127.0.0.1:3080"}, cookie=cookie)
        assert dispatched.status == 200
        payload = json.loads(bytes(dispatched.body).decode("utf-8"))
        assert payload["type"] == "server-response"
        assert payload["rpcId"] == "r1"
        assert payload["result"]["ok"] is True
    finally:
        await ctx.fiber.dispose()
