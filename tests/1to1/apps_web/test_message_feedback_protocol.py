"""
1:1 mapping of `reference/apps/web/tests/message-feedback-protocol.snapshot.ts`
(the `messageFeedback` Host Remote protocol case).

The reference launches the shipped Web scaffold, seeds the recorded Session
fixture (`snapshots/web/message-feedback-protocol/session.jsonl`), POSTs the
seven recorded exchanges to `/api/messageFeedback/{put,list,delete}` and
compares a normalized transcript against
`snapshots/web/message-feedback-protocol/protocol.expected.json`.

This port boots the same shipped composition (`build_harness(mode="web")`
mounts the webserver, the apiproxy carrier, the connection service, the
frontend-static fallback owner and the message-feedback row), seeds the same
recorded Session through the profile's own JSONL persistence, and drives the
same seven exchanges through the served `/api` handler, which is the handler
the webserver's `/api` prefix route dispatches to over a real socket.

Only run-owned values are normalized (the addressed message id, the created
item version, and the two Host timestamps); every protocol name, status, error
message and business field stays exact.
"""

import asyncio
import json
import os
import re

import pytest

from dsh.core.session.types import SessionId
from dsh.harness import build_harness
from dsh.host.webserver.webserver import HttpResponseWriter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SNAPSHOT_DIR = os.path.join(REPO_ROOT, "snapshots", "web", "message-feedback-protocol")
SESSION_FIXTURE = os.path.join(SNAPSHOT_DIR, "session.jsonl")
PROTOCOL_EXPECTED = os.path.join(SNAPSHOT_DIR, "protocol.expected.json")
SESSION_ID = "message-feedback-protocol"

UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class RecordingStream:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        pass

    def close(self):
        pass


def load_fixture_events():
    """Decode the recorded Session log into header metadata plus events."""
    header = None
    events = []
    with open(SESSION_FIXTURE, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") == "session":
                header = record
                continue
            events.append(record)
    assert header is not None, "the recorded Session fixture carries no header"
    return header, events


async def seed_session(ctx, cwd):
    """
    Seed the recorded Session through the composition's own persistence.

    The recorded fixture is an authored log, so it is appended verbatim (minus
    its `seq` numbering, which persistence assigns) and the header is written
    with the fixture's own `createdAt`, with `{{cwd}}` tokenized to a run-owned
    directory exactly like the reference scaffold's fixture identities.
    """
    header, records = load_fixture_events()
    persistence = ctx.get("sessionPersistence") or ctx.get("session_persistence")
    session_id = SessionId(SESSION_ID)
    from dsh.core.session.types import SessionHeader

    meta = SessionHeader(session_id=session_id, created_at=header["createdAt"], cwd=cwd)
    await persistence.create(meta)
    events = []
    for index, record in enumerate(records):
        event = dict(record)
        event["seq"] = index
        event.setdefault("time", header["createdAt"])
        events.append(event)
    await persistence.append(session_id, events)
    return session_id


async def invoke(apiproxy, session_id, rpc_id, endpoint, request):
    """POST one recorded exchange through the served `/api` handler."""
    body = {
        "type": "client-request",
        "rpcId": rpc_id,
        "method": endpoint,
        "payload": {"args": {"request": request}},
    }
    response = HttpResponseWriter(RecordingStream())
    await apiproxy._handle_api_request(
        {
            "method": "POST",
            "path": "/api/" + endpoint,
            "query": "",
            "raw_url": "/api/" + endpoint,
            "headers": {"content-type": "application/json"},
            "body": json.dumps(body).encode("utf-8"),
        },
        response,
    )
    await response.finish()
    payload = json.loads(bytes(response.body).decode("utf-8"))
    return {
        "endpoint": "/api/" + endpoint,
        "request": body["payload"],
        "status": response.status,
        "response": payload,
    }


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
    previous_home = os.environ.get("DSH_HOME")
    os.environ["DSH_HOME"] = str(tmp_path / "home")
    try:
        ctx = build_harness(mode="web", enable_web=True, verbose=False)
        service = ctx.get("messageFeedback")
        assert service is not None, "the shipped web composition mounted no messageFeedback provider"
        # The plugin starts its domain open as a task on the active loop.
        while service._table is None:
            await asyncio.sleep(0)

        session_id = await seed_session(ctx, str(tmp_path))
        apiproxy = ctx.get("apiproxy")
        message_id = None
        with open(SESSION_FIXTURE, "r", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("type") == "assistant/message":
                    message_id = record["data"]["message"]["id"]
        assert message_id and message_id.startswith("{{message:2}}")

        # The recorded fixture is an authored log: its `{{message:2}}` token is
        # resolved to the id persistence assigned the recorded assistant event.
        persisted = await (ctx.get("sessionPersistence") or ctx.get("session_persistence")).inspect(session_id)
        assistant_events = [
            event
            for event in persisted.events
            if event.get("type") == "assistant/message"
            and (event.get("data") or {}).get("message", {}).get("id")
        ]
        assert assistant_events, "the seeded Session lost its assistant projection"
        message_id = assistant_events[0]["data"]["message"]["id"]

        exchanges = []
        exchanges.append(
            await invoke(
                apiproxy,
                session_id,
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
            await invoke(
                apiproxy, session_id, "feedback-list-empty", "messageFeedback/list", {"sessionId": SESSION_ID}
            )
        )
        created = await invoke(
            apiproxy,
            session_id,
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
            await invoke(
                apiproxy, session_id, "feedback-list-created", "messageFeedback/list", {"sessionId": SESSION_ID}
            )
        )
        exchanges.append(
            await invoke(
                apiproxy,
                session_id,
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
                apiproxy,
                session_id,
                "feedback-delete",
                "messageFeedback/delete",
                {"sessionId": SESSION_ID, "messageId": message_id, "ifVersion": version},
            )
        )
        exchanges.append(
            await invoke(
                apiproxy, session_id, "feedback-list-deleted", "messageFeedback/list", {"sessionId": SESSION_ID}
            )
        )

        assert all(exchange["status"] == 200 for exchange in exchanges)
        actual = normalize_protocol(exchanges, version, message_id)
        expected = open(PROTOCOL_EXPECTED, "r", encoding="utf-8").read()
        assert json.loads(actual) == json.loads(expected)

        # `assertFixtureInventory(SNAPSHOT_DIR, ['protocol.expected.json', 'session.jsonl'])`
        from .snapshot_fixtures import assertFixtureInventory

        assertFixtureInventory(SNAPSHOT_DIR, ["protocol.expected.json", "session.jsonl"])
    finally:
        if previous_home is None:
            os.environ.pop("DSH_HOME", None)
        else:
            os.environ["DSH_HOME"] = previous_home


def test_fixture_inventory_is_mirrored_verbatim():
    """`assertFixtureInventory(SNAPSHOT_DIR, ['protocol.expected.json', 'session.jsonl'])`."""
    from .snapshot_fixtures import assertFixtureInventory

    assertFixtureInventory(SNAPSHOT_DIR, ["protocol.expected.json", "session.jsonl"])
