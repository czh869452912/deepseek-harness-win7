"""
1:1 mapping of `reference/apps/web/tests/message-feedback-protocol.snapshot.ts`
(the `messageFeedback` Host Remote protocol case).

The reference launches the shipped Web scaffold, seeds the recorded Session
fixture (`snapshots/web/message-feedback-protocol/session.jsonl`), POSTs the
seven recorded exchanges to `/api/messageFeedback/{put,list,delete}` **over the
bound port** with the browser-session cookie
(`scaffold.hostFetch` -> `fetch(new URL(path, baseUrl), { headers: { cookie } })`),
and compares a normalized transcript against
`snapshots/web/message-feedback-protocol/protocol.expected.json`.

This port boots the same shipped composition (`build_harness(mode="web")` mounts
the webserver, the apiproxy carrier, the connection service, the frontend-static
fallback owner and the message-feedback row), starts the real carrier, performs
the same launch-token exchange the browser performs
(`ctx.connection.authenticatedUrl` -> `GET /?token=...` -> 303 + session
cookie), and then drives the same seven exchanges as raw HTTP/1.1 requests
against `/api/messageFeedback/*` — so the case covers the authenticated socket
path, not just the handler.

The seed is the reference's own: the fixture's `{{message:N}}` identities are
realized through `fixtureIdentity` (`scaffold.ts:930`), event times are
materialized from event order against the fixture header
(`scaffold.ts:1042`), and the log is written through the composition's own
JSONL persistence (`persistSeedSession`). The reference seeds through a
throwaway Context holding the same persistence root; this port seeds through
the booted composition's `sessionPersistence` row, which is the same root and
the same backend API.

Only run-owned values are normalized (the addressed message id, the created
item version, and the two Host timestamps); every protocol name, status, error
message and business field stays exact.

The wire boundary the recorded exchanges move through is the Typert Remote
gateway (`reference/packages/api/gateway/src/index.ts`): `remoteRequest`'s
payload shape, `assertExactArguments`' exact wire fields, and the generated
strict codec per declared field. The cases at the end of this module pin that
boundary for the three messageFeedback methods.
"""

import asyncio
import hashlib
import json
import os
import re

import pytest

from dsh.core.session.types import SessionHeader, SessionId
from canonical_web_fixture import web_context
from dsh.host.apiproxy.api.message_feedback import (
    MessageFeedbackDomainHandler,
    TypertGatewayError,
    endpoint_request,
    validate_wire_request,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SNAPSHOT_DIR = os.path.join(REPO_ROOT, "snapshots", "web", "message-feedback-protocol")
SESSION_FIXTURE = os.path.join(SNAPSHOT_DIR, "session.jsonl")
PROTOCOL_EXPECTED = os.path.join(SNAPSHOT_DIR, "protocol.expected.json")
SESSION_ID = "message-feedback-protocol"

UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def fixture_identity(kind, ordinal):
    """`fixtureIdentity(kind, ordinal)` (`scaffold.ts:930`), byte for byte."""
    digits = list(hashlib.sha256(("%s:%d" % (kind, ordinal)).encode("utf-8")).hexdigest()[:32])
    digits[12] = "4"
    digits[16] = ["8", "9", "a", "b"][int(digits[16], 16) % 4]
    joined = "".join(digits)
    return "%s-%s-%s-%s-%s" % (
        joined[0:8],
        joined[8:12],
        joined[12:16],
        joined[16:20],
        joined[20:],
    )


MESSAGE_ID = fixture_identity("message", 2)


def realize_seed_fixture(fixture_text, session_id, cwd):
    """
    `realizeSeedFixture` (`scaffold.ts:968`): placeholders, then the recorded cwd.

    The reference substitutes the workspace path into the raw JSONL text, which
    only yields parseable JSON while the workspace is a POSIX path. A Windows
    temp directory contains backslashes, so the substituted value is the JSON
    string body of that path instead: the document decodes to exactly the same
    workspace, on either separator convention. Every other token is an
    identifier and needs no escaping.
    """
    escaped_cwd = json.dumps(cwd, ensure_ascii=False)[1:-1]
    realized = fixture_text.replace("{{sessionId}}", session_id).replace("{{session:1}}", session_id)
    realized = re.sub(
        r"\{\{session:([2-9]\d*)\}\}", lambda match: "%s-child-%s" % (session_id, match.group(1)), realized
    )
    realized = re.sub(
        r"\{\{(message|approval|workflow|command|rpc|retry|id):([1-9]\d*)\}\}",
        lambda match: fixture_identity(match.group(1), int(match.group(2))),
        realized,
    )
    realized = realized.replace("{{cwd}}", escaped_cwd)
    fixture_cwd = json.loads(realized.split("\n", 1)[0]).get("cwd")
    if fixture_cwd is None:
        return realized
    return realized.replace(json.dumps(fixture_cwd, ensure_ascii=False)[1:-1], escaped_cwd)


def parse_seed_fixture(fixture_text):
    """`parseSeedFixture` (`scaffold.ts:987`): header line, header, logical events."""
    lines = [line for line in fixture_text.split("\n") if line.strip()]
    assert lines, "seed fixture has no session header"
    header = json.loads(lines[0])
    assert header.get("type") == "session", "seed fixture must start with a session header"
    events = [json.loads(line) for line in lines[1:]]
    return header, events


async def seed_session(ctx, cwd):
    """
    `seedSession` (`scaffold.ts:1016`): realize, materialize times, persist.

    The reference insists a committed seed is a closed recording; the same
    refusal is kept here so an open final turn cannot be silently repaired by a
    resume.
    """
    with open(SESSION_FIXTURE, "r", encoding="utf-8", newline="") as handle:
        fixture_text = handle.read()
    header, events = parse_seed_fixture(realize_seed_fixture(fixture_text, SESSION_ID, cwd))
    assert events, "seed fixture has no events"
    assert events[-1].get("type") == "turn/end", "seed fixture must end in turn/end"

    persistence = ctx.get("sessionPersistence") or ctx.get("session_persistence")
    session_id = SessionId(SESSION_ID)
    meta = SessionHeader(session_id=session_id, created_at=header["createdAt"], cwd=cwd)
    fixture_created_at = header["createdAt"]
    time_anchor = meta.createdAt if fixture_created_at == 0 else fixture_created_at
    materialized = []
    for index, event in enumerate(events):
        record = dict(event)
        record["seq"] = index
        record["time"] = time_anchor + index
        materialized.append(record)
    await persistence.create(meta)
    await persistence.append(session_id, materialized)
    return session_id


async def raw_request(port, method, path, headers=None, body=None):
    """One real HTTP/1.1 request against the bound carrier: (status, headers, body)."""
    lines = ["%s %s HTTP/1.1" % (method, path), "Host: 127.0.0.1", "Connection: close"]
    for key, value in (headers or {}).items():
        lines.append("%s: %s" % (key, value))
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("utf-8"))
        if body is not None:
            writer.write(body)
        await writer.drain()
        head_bytes = await reader.readuntil(b"\r\n\r\n")
        status_line, _, raw_headers = head_bytes.partition(b"\r\n")
        status = int(status_line.split(b" ")[1])
        response_headers = {}
        for line in raw_headers.decode("latin-1").split("\r\n"):
            if ":" in line:
                key, _, value = line.partition(":")
                response_headers[key.strip().lower()] = value.strip()
        payload = await reader.read()
        return status, response_headers, payload
    finally:
        writer.close()


class ServedWebHost:
    """
    One bound, authenticated shipped Web Host: real carrier, real cookie.

    `hostFetch` in the reference scaffold is the same shape — a `fetch` against
    the scaffold's own `baseUrl` carrying the cookie from the launch exchange.
    """

    def __init__(self, ctx, server, port, cookie):
        self.ctx = ctx
        self.server = server
        self.port = port
        self.cookie = cookie

    async def post(self, rpc_id, endpoint, payload):
        """One `client-request` envelope POSTed at `/api/<endpoint>`."""
        body = json.dumps(
            {
                "type": "client-request",
                "rpcId": rpc_id,
                "method": endpoint,
                "payload": payload,
            }
        ).encode("utf-8")
        status, _, response = await raw_request(
            self.port,
            "POST",
            "/api/" + endpoint,
            {
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "Cookie": self.cookie,
            },
            body,
        )
        return status, json.loads(response.decode("utf-8"))

    async def close(self):
        from canonical_web_fixture import close_web_context
        await close_web_context(self.ctx)


async def launch_served_host(tmp_path):
    """
    Boot the shipped composition, seed the fixture, bind the carrier, and run
    the browser's own launch-token exchange over a real socket.

    This is `launchWebScaffold` + `seedSession` restricted to what the protocol
    case needs: the port's `web` composition mounts the webserver, the apiproxy
    carrier, the connection service, the frontend-static fallback owner and the
    message-feedback row.
    """
    ctx = await web_context(tmp_path / "host")
    service = ctx.get("messageFeedback")
    assert service is not None, "the shipped web composition mounted no messageFeedback provider"
    # The plugin opens its domain as a task on the active loop.
    while service._table is None:
        await asyncio.sleep(0)
    await seed_session(ctx, str(tmp_path))

    server = ctx.get("webServer")
    await server.start()
    connection = ctx.get("connection")
    launch = connection.authenticated_url("http://127.0.0.1:%d" % server.listened_port)
    token = launch.split("token=", 1)[1]
    status, headers, _ = await raw_request(server.listened_port, "GET", "/?token=" + token)
    assert status == 303, "launch-token exchange did not redirect"
    assert headers.get("location") == "/"
    cookie = headers["set-cookie"].split(";", 1)[0]
    assert cookie, "launch-token exchange returned an empty session cookie"
    return ServedWebHost(ctx, server, server.listened_port, cookie)


def created_version(response):
    """Extract the opaque item version while every surrounding wire field stays exact."""
    result = response.get("result")
    assert isinstance(result, dict) and result.get("ok") is True, response
    outer = result.get("value")
    assert isinstance(outer, dict) and outer.get("ok") is True, response
    item = outer.get("value")
    assert isinstance(item, dict) and isinstance(item.get("version"), str), response
    return item["version"]


def normalize_protocol(exchanges, version, message_id):
    """Replace only run-owned UUID/time values; all protocol names stay exact."""

    def walk(value, key=None):
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        if key == "messageId" and value == message_id:
            return "{{message:2}}"
        if key in ("version", "ifVersion") and value == version:
            return "{{version}}"
        if key in ("createdAt", "updatedAt") and isinstance(value, int):
            return "{{timestamp}}"
        return value

    return json.dumps(walk(exchanges), indent=2)


@pytest.mark.asyncio
async def test_snapshots_strict_list_put_conflict_and_delete_calls_through_the_shipped_web_host(tmp_path):
    """`it('snapshots strict list, put, conflict, and delete calls through the shipped Web Host')`."""
    previous_home = os.environ.get("DSH_HOME")
    os.environ["DSH_HOME"] = str(tmp_path / "home")
    host = None
    try:
        host = await launch_served_host(tmp_path)
        ctx = host.ctx
        message_id = MESSAGE_ID
        persisted = await (ctx.get("sessionPersistence") or ctx.get("session_persistence")).inspect(
            SessionId(SESSION_ID)
        )
        assistant_ids = [
            ((event.get("data") or {}).get("message") or {}).get("id")
            for event in persisted.events
            if event.get("type") == "assistant/message"
        ]
        assert message_id in assistant_ids, assistant_ids

        # The route that serves the protocol is behind the connection's auth
        # fence: without the browser cookie the same POST is refused, so the
        # exchanges below really travel the served, authenticated `/api` route.
        unauth = json.dumps(
            {
                "type": "client-request",
                "rpcId": "feedback-unauth",
                "method": "messageFeedback/list",
                "payload": {"args": {"request": {"sessionId": SESSION_ID}}},
            }
        ).encode("utf-8")
        status, _, _ = await raw_request(
            host.port,
            "POST",
            "/api/messageFeedback/list",
            {"Content-Type": "application/json", "Content-Length": str(len(unauth))},
            unauth,
        )
        assert status == 401, "the /api carrier answered an unauthenticated request"

        async def invoke(rpc_id, endpoint, request):
            status, payload = await host.post(rpc_id, endpoint, {"args": {"request": request}})
            return {
                "endpoint": "/api/" + endpoint,
                "request": {"args": {"request": request}},
                "status": status,
                "response": payload,
            }

        exchanges = []
        exchanges.append(
            await invoke(
                "feedback-invalid",
                "messageFeedback/put",
                {
                    "sessionId": SESSION_ID,
                    "messageId": message_id,
                    "rating": "invalid-rating",
                    "ifVersion": None,
                },
            )
        )
        exchanges.append(
            await invoke("feedback-list-empty", "messageFeedback/list", {"sessionId": SESSION_ID})
        )
        created = await invoke(
            "feedback-put",
            "messageFeedback/put",
            {
                "sessionId": SESSION_ID,
                "messageId": message_id,
                "rating": "positive",
                "note": "Useful answer",
                "ifVersion": None,
            },
        )
        exchanges.append(created)
        version = created_version(created["response"])
        assert UUID_V4.match(version), version
        exchanges.append(
            await invoke("feedback-list-created", "messageFeedback/list", {"sessionId": SESSION_ID})
        )
        exchanges.append(
            await invoke(
                "feedback-conflict",
                "messageFeedback/put",
                {
                    "sessionId": SESSION_ID,
                    "messageId": message_id,
                    "rating": "negative",
                    "ifVersion": None,
                },
            )
        )
        exchanges.append(
            await invoke(
                "feedback-delete",
                "messageFeedback/delete",
                {"sessionId": SESSION_ID, "messageId": message_id, "ifVersion": version},
            )
        )
        exchanges.append(
            await invoke("feedback-list-deleted", "messageFeedback/list", {"sessionId": SESSION_ID})
        )

        assert all(exchange["status"] == 200 for exchange in exchanges)
        actual = normalize_protocol(exchanges, version, message_id)
        with open(PROTOCOL_EXPECTED, "r", encoding="utf-8") as handle:
            expected = handle.read()
        assert json.loads(actual) == json.loads(expected)

        # `assertFixtureInventory(SNAPSHOT_DIR, ['protocol.expected.json', 'session.jsonl'])`
        from .snapshot_fixtures import assertFixtureInventory

        assertFixtureInventory(SNAPSHOT_DIR, ["protocol.expected.json", "session.jsonl"])
    finally:
        if host is not None:
            await host.close()
        if previous_home is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = previous_home


def test_fixture_inventory_is_mirrored_verbatim():
    """`assertFixtureInventory(SNAPSHOT_DIR, ['protocol.expected.json', 'session.jsonl'])`."""
    from .snapshot_fixtures import assertFixtureInventory

    assertFixtureInventory(SNAPSHOT_DIR, ["protocol.expected.json", "session.jsonl"])


@pytest.mark.asyncio
async def test_the_served_api_answers_malformed_remote_payloads_with_the_gateway_envelope(tmp_path):
    """
    The payload, args, and field refusals over the served, authenticated socket.

    The reference observes these at its own `/api` route: the generic gateway
    case (`gateway.host.spec.ts`: `mounts a shared /api interceptor through an
    optional Connection and returns existing RPC results`) POSTs a malformed
    payload over a real fetch carrying a browser cookie and asserts
    `result.error.code === 'internal'` with the `plain-object args field`
    message. Every failure here is that envelope on HTTP 200, never a transport
    error, and the business union still travels inside a successful envelope.
    """
    previous_home = os.environ.get("DSH_HOME")
    os.environ["DSH_HOME"] = str(tmp_path / "home")
    host = None
    try:
        host = await launch_served_host(tmp_path)
        put_request = {
            "sessionId": SESSION_ID,
            "messageId": MESSAGE_ID,
            "rating": "positive",
            "ifVersion": None,
        }
        cases = [
            (
                "rpc-payload",
                "messageFeedback/list",
                {"invalid": True},
                "Remote payload must contain exactly "
                "one plain-object args field",
            ),
            (
                "rpc-args",
                "messageFeedback/list",
                {"args": {}},
                "typert gateway: messageFeedback/list: args fields do not match the descriptor: "
                'missing "request"',
            ),
            (
                "rpc-extra-args",
                "messageFeedback/list",
                {"args": {"request": {"sessionId": SESSION_ID}, "sessionId": SESSION_ID}},
                "typert gateway: messageFeedback/list: args fields do not match the descriptor: "
                'unexpected "sessionId"',
            ),
            (
                "rpc-rating",
                "messageFeedback/put",
                {"args": {"request": dict(put_request, rating="invalid-rating")}},
                'typert gateway: messageFeedback/put: wire field "request" failed boundary validation',
            ),
            (
                # `ifVersion` is required by presence on put.
                "rpc-missing-ifversion",
                "messageFeedback/put",
                {"args": {"request": {k: v for k, v in put_request.items() if k != "ifVersion"}}},
                'typert gateway: messageFeedback/put: wire field "request" failed boundary validation',
            ),
            (
                # `z.string().optional()` admits absence, never an explicit null.
                "rpc-null-note",
                "messageFeedback/put",
                {"args": {"request": dict(put_request, note=None)}},
                'typert gateway: messageFeedback/put: wire field "request" failed boundary validation',
            ),
            (
                "rpc-null-delete-ifversion",
                "messageFeedback/delete",
                {"args": {"request": {
                    "sessionId": SESSION_ID, "messageId": MESSAGE_ID, "ifVersion": None,
                }}},
                'typert gateway: messageFeedback/delete: wire field "request" failed boundary validation',
            ),
        ]
        for rpc_id, endpoint, payload, message in cases:
            status, response = await host.post(rpc_id, endpoint, payload)
            assert status == 200, rpc_id
            assert response == {
                "type": "server-response",
                "rpcId": rpc_id,
                "result": {
                    "ok": False,
                    "error": {"code": "internal", "message": message, "details": {}},
                },
            }, rpc_id

        # An id brand has no runtime refinement, so an empty id is boundary-legal
        # and the business union judges it — still inside a successful envelope.
        status, response = await host.post(
            "rpc-empty-id", "messageFeedback/list", {"args": {"request": {"sessionId": ""}}}
        )
        assert status == 200
        assert response == {
            "type": "server-response",
            "rpcId": "rpc-empty-id",
            "result": {
                "ok": True,
                "value": {"ok": False, "error": {"code": "session-not-found", "sessionId": ""}},
            },
        }
    finally:
        if host is not None:
            await host.close()
        if previous_home is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = previous_home


def test_fixture_identities_realize_like_the_scaffold():
    """
    `realizeSeedFixture` (`scaffold.ts:968`) plus `fixtureIdentity` (`scaffold.ts:930`).

    The seeded log must carry the deterministic identity the reference computes
    for `{{message:2}}`, not the placeholder text.
    """
    with open(SESSION_FIXTURE, "r", encoding="utf-8", newline="") as handle:
        fixture_text = handle.read()
    realized = realize_seed_fixture(fixture_text, SESSION_ID, "C:/ws")
    assert "{{" not in realized
    header, events = parse_seed_fixture(realized)
    assert header["id"] == SESSION_ID
    assert header["cwd"] == "C:/ws"
    assert [event["data"]["message"]["id"] for event in events if event["type"] == "assistant/message"] == [
        MESSAGE_ID
    ]
    assert UUID_V4.match(MESSAGE_ID), MESSAGE_ID
    # The reference's own worked value for this fixture is recomputed from the
    # hash rule, so a drift in either the rule or the fixture shows up here.
    assert MESSAGE_ID == fixture_identity("message", 2)
    assert fixture_identity("message", 1)[14] == "4"
    assert fixture_identity("message", 1)[19] in "89ab"


# --------------------------------------------------------------------------
# The wire boundary (source-derived)
#
# `reference/packages/api/gateway/tests/gateway.host.spec.ts` owns these rules
# generically (`mounts a shared /api interceptor through an optional Connection
# and returns existing RPC results` — the payload-shape refusal over a real
# `/api` route with a browser cookie; `requires exact wire fields before
# invoking business code` — the args-key refusal). This unit serves one
# namespace of that gateway, so the cases below pin the same rules where the
# messageFeedback methods are observed. They are source-derived, not copies of
# an upstream case title.
# --------------------------------------------------------------------------


def _boundary_failure(method, request):
    with pytest.raises(TypertGatewayError) as raised:
        validate_wire_request(method, request)
    assert raised.value.code == "input-invalid"
    assert raised.value.message == 'wire field "request" failed boundary validation'
    assert str(raised.value) == (
        'typert gateway: messageFeedback/%s: wire field "request" failed boundary validation' % method
    )
    return raised.value


def test_generated_codecs_accept_any_string_brand_and_require_their_fields():
    """
    `z.intersection(z.string(), z.unknown())` for every branded id.

    `SessionId`, `MessageId` and `MessageFeedbackVersion` are type-only brands
    (`reference/packages/util/brand/src/index.ts`), so the generated codec has
    no runtime refinement: `''` is boundary-legal input the business union then
    judges (`session-not-found`), never a boundary failure.
    """
    assert validate_wire_request("list", {"sessionId": ""}) == {"sessionId": ""}
    assert validate_wire_request("put", {
        "sessionId": "",
        "messageId": "",
        "rating": "positive",
        "ifVersion": "",
    }) == {"sessionId": "", "messageId": "", "rating": "positive", "ifVersion": ""}
    assert validate_wire_request("delete", {
        "sessionId": "",
        "messageId": "",
        "ifVersion": "",
    }) == {"sessionId": "", "messageId": "", "ifVersion": ""}

    # Required by presence, for every declared non-optional field.
    for request in ({}, {"sessionId": None}, {"sessionId": 1}, {"sessionId": ["s"]}):
        _boundary_failure("list", request)
    # Unknown fields are stripped, not rejected: a list request carrying a
    # stray field is still a legal list request.
    assert validate_wire_request("list", {"sessionId": "s", "messageId": "m"}) == {"sessionId": "s"}
    for request in (
        {},
        {"sessionId": "s"},
        {"sessionId": "s", "messageId": "m"},
        # `ifVersion` is `Version` here, so a present `null` is not an absent
        # optional: the delete request has no nullable slot.
        {"sessionId": "s", "messageId": "m", "ifVersion": None},
    ):
        _boundary_failure("delete", request)
    for request in (
        {},
        {"sessionId": "s"},
        {"sessionId": "s", "messageId": "m"},
        {"sessionId": "s", "messageId": "m", "rating": "positive"},
        {"sessionId": "s", "messageId": "m", "ifVersion": None},
    ):
        _boundary_failure("put", request)

    # The complete delete request is what the golden's sixth exchange sends.
    assert validate_wire_request("delete", {
        "sessionId": "s", "messageId": "m", "ifVersion": "v",
    }) == {"sessionId": "s", "messageId": "m", "ifVersion": "v"}

    # A present `null` is never a string, and never an absent optional.
    _boundary_failure("put", {
        "sessionId": "s", "messageId": "m", "rating": "positive", "ifVersion": None, "note": None,
    })


def test_put_decodes_the_declared_closed_rating_and_nullable_version():
    """
    `rating` is the closed literal union; `ifVersion` is `Version | null`.

    The absent `note` stays absent (so the business layer keeps distinguishing
    'no note' from the empty-string note it rejects as `note-blank`), unknown
    fields are stripped rather than rejected, and a `null` `ifVersion` is the
    wire's 'require that no item exists'.
    """
    decoded = validate_wire_request("put", {
        "sessionId": "s",
        "messageId": "m",
        "rating": "negative",
        "ifVersion": None,
        "unknown": "dropped",
    })
    assert decoded == {"sessionId": "s", "messageId": "m", "rating": "negative", "ifVersion": None}

    assert validate_wire_request("put", {
        "sessionId": "s", "messageId": "m", "rating": "positive", "note": "", "ifVersion": "v",
    })["note"] == ""

    for rating in ("invalid-rating", "Positive", "", "pos", None, 1, True, ["positive"], {"rating": 1}):
        with pytest.raises(TypertGatewayError):
            validate_wire_request("put", {
                "sessionId": "s", "messageId": "m", "rating": rating, "ifVersion": None,
            })

    for non_string_note in (None, 1, True, ["n"], {"n": 1}):
        with pytest.raises(TypertGatewayError):
            validate_wire_request("put", {
                "sessionId": "s", "messageId": "m", "rating": "positive", "note": non_string_note,
                "ifVersion": None,
            })


def test_payload_and_args_shapes_are_refused_before_any_field_is_decoded():
    """
    `remoteRequest` then `assertExactArguments`.

    The payload is exactly one plain-object `args` field; `args` declares
    exactly the descriptor's wire fields. Both are `internal` at the carrier
    (`rpcFailure`) with their own messages, before any business code runs.
    """
    for payload in (None, [], "args", 1, {}, {"only": True}, {"args": None}, {"args": []},
                    {"args": {}, "extra": True}):
        with pytest.raises(TypertGatewayError) as raised:
            endpoint_request("put", payload)
        assert raised.value.message == "Remote payload must contain exactly one plain-object args field"

    with pytest.raises(TypertGatewayError) as raised:
        endpoint_request("put", {"args": {}})
    assert raised.value.message == 'args fields do not match the descriptor: missing "request"'

    with pytest.raises(TypertGatewayError) as raised:
        endpoint_request("put", {"args": {"request": {}, "sessionId": "s"}})
    assert raised.value.message == 'args fields do not match the descriptor: unexpected "sessionId"'

    with pytest.raises(TypertGatewayError) as raised:
        endpoint_request("put", {"args": {"sessionId": "s"}})
    assert raised.value.message == (
        'args fields do not match the descriptor: missing "request"; unexpected "sessionId"'
    )

    assert endpoint_request("put", {"args": {"request": {"sessionId": "s"}}}) == {"sessionId": "s"}


@pytest.mark.asyncio
async def test_an_unmounted_namespace_and_an_unexported_method_are_refused():
    """`resolveDescriptor`: nothing exported this endpoint (the reference's message)."""
    handler = MessageFeedbackDomainHandler(_NoServices())
    for method in ("put", "list", "delete"):
        with pytest.raises(TypertGatewayError) as raised:
            await handler.invoke(method, {"args": {"request": {"sessionId": "s"}}})
        assert raised.value.code == "invocation-unavailable"
        assert raised.value.message == "no active Remote method exports this endpoint"
    with pytest.raises(TypertGatewayError) as raised:
        await handler.invoke("archive", {"args": {"request": {"sessionId": "s"}}})
    assert raised.value.message == "no active Remote method exports this endpoint"
    assert str(raised.value) == (
        "typert gateway: messageFeedback/archive: no active Remote method exports this endpoint"
    )


class _NoServices:
    def get(self, name):
        return None
