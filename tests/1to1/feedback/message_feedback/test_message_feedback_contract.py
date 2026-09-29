"""
1:1 mapping of `reference/packages/feedback/message-feedback/tests/message-feedback.spec.ts`
(`@deepseek-ai/dsh-message-feedback`).

Upstream cases (`MessageFeedbackService public contract`):

  - ``publishes the exact Gateway namespace and Remote method names``
  - ``returns session-not-found only for a definitive persistence miss``
  - ``rechecks live ownership before returning a cold catalog miss``
  - ``returns session-not-found from mutations and conflicts on an observed
    version for an absent item``
  - ``creates, updates, and retry-reads immutable items with monotonic Host
    times``
  - ``reports non-blank and complete UTF-8 byte limits without touching
    persistence``
  - ``accepts only non-empty append-origin assistant projections as targets``
  - ``fails invalid direct configuration and a read before domain initialization``
  - ``rejects durable rows with duplicate message ids or reused item versions``

Upstream cases (`MessageFeedbackService item concurrency`):

  - ``serializes whole-row writes while keeping versions independent per message``
  - ``rejects a stale put even when the current value has returned to the same
    state``
  - ``makes delete retries stable and prevents delete/recreate ABA``
  - ``fences a reused Session id and lets the new lifecycle start cleanly``
  - ``drains admitted mutations before domain close and rejects later admission``

Upstream cases (`MessageFeedbackService durability ordering`):

  - ``rejects a logical target missing from the cold physical durable prefix``
  - ``commits and physically verifies a live target checkpoint before the
    sidecar write``
  - ``fails closed when a live checkpoint fails, has no participant, or is not
    physically durable``
  - ``finishes the captured live checkpoint when the Session detaches mid-flush``

Port notes (recorded as `LEGAL_ADAPTATION`):

  - `Object.freeze` maps onto the port's `FrozenDict`/`FrozenList`
    (`dsh/core/session/json.py`), which stay `dict`/`list` instances for
    `json.dumps`, so ``is_frozen`` keeps the reference's
    ``Object.isFrozen(...)`` assertions observable.
  - `vi.setSystemTime` maps onto the module clock seam
    (`dsh.feedback.message_feedback._now_ms`).
  - The reference's `ctx.messageFeedback.typertRemote` binding belongs to the
    Typert Remote layer, which the port deliberately does not carry
    (`dsh/typert/registry.py` header). The namespace/method-name half of that
    case is asserted against the served RPC surface instead.
"""

import asyncio
import re

import pytest

from dsh.core.session.json import FrozenDict, FrozenList
from dsh.feedback.message_feedback import MessageFeedbackService
from dsh.feedback.message_feedback_spec import (
    parse_message_feedback_row,
)
from dsh.host.apiproxy.api.rpc_map import OFFICIAL_RPC_METHODS
from dsh.session.persistence import SessionInspection

from .helpers import append_message_fixture, message_fixture, setup_harness

STALE_VERSION = "0f8a6d2e-9d31-4c0a-8b18-1f2a4d5b7c90"


def is_frozen(value):
    return isinstance(value, (FrozenDict, FrozenList))


def expect_item(result):
    """Mirror the reference harness's `expectItem`."""
    assert result.get("ok") is True, result
    return result["value"]


def version_conflict_error(current):
    return {"ok": False, "error": {"code": "version-conflict", "current": current}}


@pytest.mark.asyncio
async def test_publishes_the_exact_gateway_namespace_and_remote_method_names():
    """
    Upstream asserts `ctx.messageFeedback.typertRemote` publishes serviceKey and
    namespace `messageFeedback` with the three direct methods list/put/delete.
    The canonical Typert Gateway consumes the binding and direct method markers.
    """
    harness = await setup_harness()
    try:
        assert harness.ctx.get("messageFeedback") is harness.service
        assert harness.ctx.get("message_feedback") is harness.service
        for method in ("list", "put", "delete"):
            assert callable(getattr(harness.service, method))
        assert {"messageFeedback.list", "messageFeedback.put", "messageFeedback.delete"} <= set(
            OFFICIAL_RPC_METHODS
        )
        from dsh.typert.remote import remote_methods
        from dsh.typert.dispatch import binding_of
        binding = binding_of(harness.service, "messageFeedback", "messageFeedback/list", "messageFeedback")
        assert binding["service"] is harness.service
        assert {item["method"] for item in remote_methods(harness.service)} == {"list", "put", "delete"}
        assert harness.service.max_note_bytes == 64
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_returns_session_not_found_only_for_a_definite_persistence_miss():
    harness = await setup_harness()
    try:
        missing = "missing-session"
        assert await harness.service.list({"sessionId": missing}) == {
            "ok": False,
            "error": {"code": "session-not-found", "sessionId": missing},
        }

        fixture = message_fixture("corrupt-session")
        harness.persistence.set_durable(
            SessionInspection(fixture.session.header, list(fixture.session.events))
        )
        corruption = RuntimeError("stored log checksum mismatch")
        harness.persistence.inspect_failure = corruption
        with pytest.raises(RuntimeError) as excinfo:
            await harness.service.list({"sessionId": fixture.session.id})
        assert excinfo.value is corruption
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_rechecks_live_ownership_before_returning_a_cold_catalog_miss():
    harness = await setup_harness()
    try:
        session_id = "catalog-live-race"
        listed = asyncio.Event()
        release = asyncio.Event()

        async def on_list_snapshots():
            listed.set()
            await release.wait()

        harness.persistence.on_list_snapshots = on_list_snapshots

        pending = asyncio.ensure_future(harness.service.list({"sessionId": session_id}))
        await listed.wait()
        harness.ctx.get("sessions").create(session_id, {"meta": {"createdAt": 1_700_000_000_001}})
        release.set()

        assert await pending == {"ok": True, "value": {"items": []}}
        assert harness.persistence.inspect_calls == 1
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_returns_session_not_found_from_mutations_and_conflicts_on_an_observed_version_for_an_absent_item():
    harness = await setup_harness()
    try:
        missing = "missing-mutations"
        missing_message = "missing-message"
        assert await harness.service.put(
            {
                "sessionId": missing,
                "messageId": missing_message,
                "rating": "positive",
                "ifVersion": None,
            }
        ) == {"ok": False, "error": {"code": "session-not-found", "sessionId": missing}}
        assert await harness.service.delete(
            {"sessionId": missing, "messageId": missing_message, "ifVersion": STALE_VERSION}
        ) == {"ok": False, "error": {"code": "session-not-found", "sessionId": missing}}

        fixture = message_fixture("absent-version-conflict")
        harness.persistence.persist(fixture.session)
        assert await harness.service.put(
            {
                "sessionId": fixture.session.id,
                "messageId": fixture.assistant_message_ids[0],
                "rating": "positive",
                "ifVersion": STALE_VERSION,
            }
        ) == {"ok": False, "error": {"code": "version-conflict", "current": None}}
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_creates_updates_and_retry_reads_immutable_items_with_monotonic_host_times(monkeypatch):
    harness = await setup_harness()
    try:
        fixture = message_fixture("timestamps")
        harness.persistence.persist(fixture.session)
        message_id = fixture.assistant_message_ids[0]

        clock = {"now": 1_700_000_001_000}
        monkeypatch.setattr(
            "dsh.feedback.message_feedback._now_ms", lambda: clock["now"]
        )

        created = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "positive",
                    "note": "  exact prose  ",
                    "ifVersion": None,
                }
            )
        )
        assert created["messageId"] == message_id
        assert created["rating"] == "positive"
        assert created["note"] == "  exact prose  "
        assert created["createdAt"] == 1_700_000_001_000
        assert created["updatedAt"] == 1_700_000_001_000
        assert re.match(r"^[0-9a-f\-]{36}$", created["version"])
        assert is_frozen(created)

        clock["now"] = 1_700_000_000_000
        updated = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "negative",
                    "ifVersion": created["version"],
                }
            )
        )
        assert updated["messageId"] == message_id
        assert updated["rating"] == "negative"
        assert updated["createdAt"] == created["createdAt"]
        assert updated["updatedAt"] == created["updatedAt"]
        assert updated["version"] != created["version"]

        retry = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "negative",
                    "ifVersion": updated["version"],
                }
            )
        )
        assert retry == updated

        listed = await harness.service.list({"sessionId": fixture.session.id})
        assert listed["ok"] is True
        assert listed["value"]["items"] == [updated]
        assert listed["value"]["items"][0] is not updated
        assert is_frozen(listed["value"])
        assert is_frozen(listed["value"]["items"])
        assert is_frozen(listed["value"]["items"][0])
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_reports_non_blank_and_complete_utf8_byte_limits_without_touching_persistence():
    harness = await setup_harness(max_note_bytes=4)
    try:
        fixture = message_fixture("note-limits")
        harness.persistence.persist(fixture.session)
        message_id = fixture.assistant_message_ids[0]
        before = harness.persistence.inspect_calls

        assert await harness.service.put(
            {
                "sessionId": fixture.session.id,
                "messageId": message_id,
                "rating": "positive",
                "note": " \n\t ",
                "ifVersion": None,
            }
        ) == {"ok": False, "error": {"code": "note-blank"}}
        assert await harness.service.put(
            {
                "sessionId": fixture.session.id,
                "messageId": message_id,
                "rating": "positive",
                "note": "\u00e9\u00e9\u00e9",
                "ifVersion": None,
            }
        ) == {
            "ok": False,
            "error": {"code": "note-too-large", "maxBytes": 4, "actualBytes": 6},
        }
        assert harness.persistence.inspect_calls == before

        expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "positive",
                    "note": "\U0001f600",
                    "ifVersion": None,
                }
            )
        )
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_accepts_only_non_empty_append_origin_assistant_projections_as_targets():
    harness = await setup_harness()
    try:
        fixture = message_fixture("targets")
        harness.persistence.persist(fixture.session)
        for message_id in (
            fixture.user_message_id,
            fixture.empty_assistant_message_id,
            fixture.replacement_assistant_message_id,
        ):
            assert await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "positive",
                    "ifVersion": None,
                }
            ) == {
                "ok": False,
                "error": {
                    "code": "target-not-found",
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                },
            }
        expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": fixture.assistant_message_ids[0],
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        )
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_fails_invalid_direct_configuration_and_a_read_before_domain_initialization():
    harness = await setup_harness()
    try:
        with pytest.raises(TypeError, match="positive safe integer"):
            MessageFeedbackService(harness.ctx, {"maxNoteBytes": 0})

        fixture = message_fixture("uninitialized-domain")
        from dsh.cordis.context import Context

        raw_ctx = Context()
        raw_ctx.provide("sessions", _FakeSessions())
        raw_ctx.provide("sessionPersistence", _FakePersistence(fixture))
        raw = MessageFeedbackService(raw_ctx, {"maxNoteBytes": 1})
        with pytest.raises(RuntimeError, match="durable domain is not initialized"):
            await raw.list({"sessionId": fixture.session.id})
    finally:
        await harness.dispose()


class _FakeSessions:
    def get(self, session_id):
        return None


class _FakePersistence:
    def __init__(self, fixture):
        self.fixture = fixture

    async def list_snapshots(self):
        return [type("Snapshot", (), {"header": self.fixture.session.header, "revision": "test"})()]

    async def inspect(self, session_id):
        return SessionInspection(self.fixture.session.header, list(self.fixture.session.events))


def test_rejects_durable_rows_with_duplicate_message_ids_or_reused_item_versions():
    version = STALE_VERSION
    with pytest.raises(ValueError) as excinfo:
        parse_message_feedback_row(
            {
                "session": {"createdAt": 1},
                "items": [
                    {
                        "messageId": "same-message",
                        "rating": "positive",
                        "version": version,
                        "createdAt": 1,
                        "updatedAt": 1,
                    },
                    {
                        "messageId": "same-message",
                        "rating": "negative",
                        "version": version,
                        "createdAt": 1,
                        "updatedAt": 1,
                    },
                ],
            }
        )
    assert str(excinfo.value) == "duplicate message feedback id 'same-message'"

    reused_version = STALE_VERSION
    with pytest.raises(ValueError) as excinfo:
        parse_message_feedback_row(
            {
                "session": {"createdAt": 1},
                "items": [
                    {
                        "messageId": "first-message",
                        "rating": "positive",
                        "version": reused_version,
                        "createdAt": 1,
                        "updatedAt": 1,
                    },
                    {
                        "messageId": "second-message",
                        "rating": "negative",
                        "version": reused_version,
                        "createdAt": 1,
                        "updatedAt": 1,
                    },
                ],
            }
        )
    assert str(excinfo.value) == "duplicate message feedback version '%s'" % reused_version


@pytest.mark.asyncio
async def test_serializes_whole_row_writes_while_keeping_versions_independent_per_message():
    harness = await setup_harness()
    try:
        fixture = message_fixture("concurrent-items")
        harness.persistence.persist(fixture.session)
        first_id, second_id = fixture.assistant_message_ids

        first_result, second_result = await asyncio.gather(
            harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": first_id,
                    "rating": "positive",
                    "ifVersion": None,
                }
            ),
            harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": second_id,
                    "rating": "negative",
                    "ifVersion": None,
                }
            ),
        )
        first = expect_item(first_result)
        second = expect_item(second_result)
        updated = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": first_id,
                    "rating": "negative",
                    "note": "changed",
                    "ifVersion": first["version"],
                }
            )
        )

        assert (
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": first_id,
                    "rating": "positive",
                    "note": "stale change",
                    "ifVersion": first["version"],
                }
            )
            == version_conflict_error(updated)
        )

        listed = await harness.service.list({"sessionId": fixture.session.id})
        assert listed["ok"] is True
        assert listed["value"]["items"] == [updated, second]
        assert listed["value"]["items"][1]["version"] == second["version"]
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_rejects_a_stale_put_even_when_the_current_value_has_returned_to_the_same_state():
    harness = await setup_harness()
    try:
        fixture = message_fixture("put-aba")
        harness.persistence.persist(fixture.session)
        message_id = fixture.assistant_message_ids[0]
        first = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        )
        second = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "negative",
                    "ifVersion": first["version"],
                }
            )
        )
        current = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "positive",
                    "ifVersion": second["version"],
                }
            )
        )

        assert (
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "positive",
                    "ifVersion": first["version"],
                }
            )
            == version_conflict_error(current)
        )
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_makes_delete_retries_stable_and_prevents_delete_recreate_aba():
    harness = await setup_harness()
    try:
        fixture = message_fixture("delete-aba")
        harness.persistence.persist(fixture.session)
        message_id = fixture.assistant_message_ids[0]
        created = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        )

        assert (
            await harness.service.delete(
                {"sessionId": fixture.session.id, "messageId": message_id, "ifVersion": STALE_VERSION}
            )
            == version_conflict_error(created)
        )
        request = {
            "sessionId": fixture.session.id,
            "messageId": message_id,
            "ifVersion": created["version"],
        }
        assert await harness.service.delete(request) == {"ok": True, "value": {"absent": True}}
        assert await harness.service.delete(request) == {"ok": True, "value": {"absent": True}}

        recreated = expect_item(
            await harness.service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": message_id,
                    "rating": "negative",
                    "ifVersion": None,
                }
            )
        )
        assert recreated["version"] != created["version"]
        assert await harness.service.delete(request) == version_conflict_error(recreated)
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_fences_a_reused_session_id_and_lets_the_new_lifecycle_start_cleanly():
    harness = await setup_harness()
    try:
        old = message_fixture("reused-session", created_at=10, cwd="/old")
        harness.persistence.persist(old.session)
        old_item = expect_item(
            await harness.service.put(
                {
                    "sessionId": old.session.id,
                    "messageId": old.assistant_message_ids[0],
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        )

        from dsh.core.session.session import Session

        replacement_header = old.session.header.to_dict() if hasattr(
            old.session.header, "to_dict"
        ) else dict(old.session.header.__dict__)
        replacement_header["createdAt"] = 20
        replacement_header["cwd"] = "/new"
        replacement = Session.create(old.session.id, list(old.session.events), replacement_header)
        harness.persistence.persist(replacement)

        assert await harness.service.list({"sessionId": replacement.id}) == {
            "ok": True,
            "value": {"items": []},
        }
        assert await harness.service.delete(
            {
                "sessionId": replacement.id,
                "messageId": old.assistant_message_ids[0],
                "ifVersion": old_item["version"],
            }
        ) == {"ok": True, "value": {"absent": True}}

        new_item = expect_item(
            await harness.service.put(
                {
                    "sessionId": replacement.id,
                    "messageId": old.assistant_message_ids[0],
                    "rating": "negative",
                    "ifVersion": None,
                }
            )
        )
        assert new_item["version"] != old_item["version"]
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_drains_admitted_mutations_before_domain_close_and_rejects_later_admission():
    harness = await setup_harness()
    try:
        fixture = message_fixture("dispose-quiescence")
        harness.persistence.persist(fixture.session)
        service = harness.service
        started = asyncio.Event()
        release = asyncio.Event()
        counters = {"physical_reads": 0, "committed": 0}

        async def on_read_from():
            counters["physical_reads"] += 1
            if counters["physical_reads"] != 1:
                return
            started.set()
            await release.wait()

        harness.persistence.on_read_from = on_read_from

        def on_changed(change):
            if getattr(change, "domain", None) == "message_feedback":
                counters["committed"] += 1

        harness.ctx.on("domain/changed", on_changed)

        first = asyncio.ensure_future(
            service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": fixture.assistant_message_ids[0],
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        )
        await started.wait()
        second = asyncio.ensure_future(
            service.put(
                {
                    "sessionId": fixture.session.id,
                    "messageId": fixture.assistant_message_ids[1],
                    "rating": "negative",
                    "ifVersion": None,
                }
            )
        )
        disposal = asyncio.ensure_future(harness.dispose_feedback())
        while service.mutation_admission_open:
            await asyncio.sleep(0)

        with pytest.raises(RuntimeError, match="message-feedback: service is disposing"):
            await service.delete(
                {
                    "sessionId": fixture.session.id,
                    "messageId": fixture.assistant_message_ids[0],
                    "ifVersion": STALE_VERSION,
                }
            )
        release.set()

        expect_item(await first)
        expect_item(await second)
        await disposal
        assert counters["physical_reads"] == 2
        assert counters["committed"] == 2
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_rejects_a_logical_target_missing_from_the_cold_physical_durable_prefix():
    harness = await setup_harness()
    try:
        fixture = message_fixture("cold-prefix")
        harness.persistence.logical[fixture.session.id] = SessionInspection(
            fixture.session.header, list(fixture.session.events)
        )
        harness.persistence.set_durable(SessionInspection(fixture.session.header, []))

        assert await harness.service.put(
            {
                "sessionId": fixture.session.id,
                "messageId": fixture.assistant_message_ids[0],
                "rating": "positive",
                "ifVersion": None,
            }
        ) == {
            "ok": False,
            "error": {
                "code": "target-not-found",
                "sessionId": fixture.session.id,
                "messageId": fixture.assistant_message_ids[0],
            },
        }
        assert harness.persistence.read_from_calls == 1
        assert await harness.service.list({"sessionId": fixture.session.id}) == {
            "ok": True,
            "value": {"items": []},
        }
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_commits_and_physically_verifies_a_live_target_checkpoint_before_the_sidecar_write():
    harness = await setup_harness()
    try:
        session = harness.ctx.get("sessions").create(
            "live-checkpoint", {"meta": {"createdAt": 30, "cwd": "/live"}}
        )
        fixture = append_message_fixture(session)
        order = []

        def on_flush(current):
            order.append("session:durable")
            harness.persistence.persist(current)

        harness.ctx.on("session/flush", on_flush)

        def on_changed(change):
            if getattr(change, "domain", None) == "message_feedback":
                order.append("sidecar:durable")

        harness.ctx.on("domain/changed", on_changed)

        def on_read_from():
            order.append("session:verified")

        harness.persistence.on_read_from = on_read_from

        expect_item(
            await harness.service.put(
                {
                    "sessionId": session.id,
                    "messageId": fixture.assistant_message_ids[0],
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        )
        assert order == ["session:durable", "session:verified", "sidecar:durable"]
        assert harness.persistence.read_from_calls == 1
        assert any(
            event.get("type") == "assistant/message"
            for event in harness.persistence.durable[session.id].events
        )
    finally:
        await harness.dispose()


@pytest.mark.asyncio
async def test_fails_closed_when_a_live_checkpoint_fails_has_no_participant_or_is_not_physically_durable():
    failed = await setup_harness()
    try:
        failed_session = failed.ctx.get("sessions").create("live-flush-failure")
        failed_fixture = append_message_fixture(failed_session)
        disk_failure = RuntimeError("disk unavailable")

        def raising_flush(_current):
            raise disk_failure

        failed.ctx.on("session/flush", raising_flush)
        with pytest.raises(RuntimeError) as excinfo:
            await failed.service.put(
                {
                    "sessionId": failed_session.id,
                    "messageId": failed_fixture.assistant_message_ids[0],
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        assert excinfo.value is disk_failure
        assert await failed.service.list({"sessionId": failed_session.id}) == {
            "ok": True,
            "value": {"items": []},
        }
    finally:
        await failed.dispose()

    absent = await setup_harness()
    try:
        absent_session = absent.ctx.get("sessions").create("live-no-flush")
        absent_fixture = append_message_fixture(absent_session)
        with pytest.raises(RuntimeError, match="no durability listener participated"):
            await absent.service.put(
                {
                    "sessionId": absent_session.id,
                    "messageId": absent_fixture.assistant_message_ids[0],
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        assert await absent.service.list({"sessionId": absent_session.id}) == {
            "ok": True,
            "value": {"items": []},
        }
    finally:
        await absent.dispose()

    no_durability = await setup_harness()
    try:
        unpersisted = no_durability.ctx.get("sessions").create("live-unpersisted")
        unpersisted_fixture = append_message_fixture(unpersisted)
        no_durability.ctx.on("session/flush", lambda _current: None)
        with pytest.raises(RuntimeError, match="not found"):
            await no_durability.service.put(
                {
                    "sessionId": unpersisted.id,
                    "messageId": unpersisted_fixture.assistant_message_ids[0],
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        assert unpersisted.id not in no_durability.persistence.durable
        assert await no_durability.service.list({"sessionId": unpersisted.id}) == {
            "ok": True,
            "value": {"items": []},
        }
    finally:
        await no_durability.dispose()


@pytest.mark.asyncio
async def test_finishes_the_captured_live_checkpoint_when_the_session_detaches_mid_flush():
    harness = await setup_harness()
    try:
        sessions = harness.ctx.get("sessions")
        session = sessions.prepare("detach-during-flush", {"meta": {"createdAt": 40, "cwd": "/detach"}})
        detach = sessions.enter(session)
        sessions.announce(session)
        fixture = append_message_fixture(session)
        started = asyncio.Event()
        release = asyncio.Event()

        async def on_flush(current):
            started.set()
            await release.wait()
            harness.persistence.persist(current)

        harness.ctx.on("session/flush", on_flush)

        pending = asyncio.ensure_future(
            harness.service.put(
                {
                    "sessionId": session.id,
                    "messageId": fixture.assistant_message_ids[0],
                    "rating": "positive",
                    "ifVersion": None,
                }
            )
        )
        await started.wait()
        detach()
        assert sessions.get(session.id) is None
        release.set()
        expect_item(await pending)
        assert harness.persistence.read_from_calls == 1
        listed = await harness.service.list({"sessionId": session.id})
        assert listed["ok"] is True
        assert listed["value"]["items"][0]["messageId"] == fixture.assistant_message_ids[0]
    finally:
        await harness.dispose()
