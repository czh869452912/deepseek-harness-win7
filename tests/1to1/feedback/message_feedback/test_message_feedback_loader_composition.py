"""
1:1 mapping of `reference/packages/feedback/message-feedback/tests/loader-composition.spec.ts`
(`message feedback through a real Loader composition`):

  - ``persists a checkpointed target and its sidecar across a cold restart``

The reference composes the row set from a `cordis.yml`
(session store, JSONL persistence rooted in the run directory, the storage hub,
the JSON backend, the domain form and the `message-feedback` row configured with
`maxNoteBytes: 32`), puts feedback on a live session, disposes the composition,
loads a second composition over the same roots and reads the sidecar back.

The port performs that same composition through plugin mounting (the port's
loader resolves the same rows; there is no YAML include layer), keeps the
reference's `maxNoteBytes: 32`, and asserts the same three observables: the
durable log carries the addressed assistant projection, the second composition
lists the very item the first committed, and the session is no longer live.
"""

import os

import pytest

from dsh.cordis.context import Context
from dsh.feedback.message_feedback import MessageFeedbackPlugin
from dsh.session.persistence_jsonl import JsonlSessionPersistencePlugin
from dsh.storage.hub import StorageService

from .helpers import append_message_fixture


async def compose(root):
    """One message-feedback composition over the run's durable roots."""
    sessions_root = os.path.join(root, "sessions")
    storage_root = os.path.join(root, "storage")
    ctx = Context()
    from dsh.core.session.session import SessionStore

    store = SessionStore(ctx)
    store.apply(ctx)
    await ctx.plugin(JsonlSessionPersistencePlugin, config={"root": sessions_root})
    StorageService(ctx, root_dir=storage_root)
    await ctx.plugin(MessageFeedbackPlugin, config={"maxNoteBytes": 32})
    return ctx


@pytest.mark.asyncio
async def test_persists_a_checkpointed_target_and_its_sidecar_across_a_cold_restart(tmp_path):
    root = str(tmp_path)

    first = await compose(root)
    assert first.get("messageFeedback") is not None
    assert first.get("messageFeedback").max_note_bytes == 32
    assert {"list", "put", "delete"} == {
        name for name in ("list", "put", "delete") if callable(getattr(first.get("messageFeedback"), name))
    }

    session = first.get("sessions").create("loader-feedback", {"meta": {"cwd": root}})
    fixture = append_message_fixture(session)
    put = await first.get("messageFeedback").put(
        {
            "sessionId": session.id,
            "messageId": fixture.assistant_message_ids[0],
            "rating": "positive",
            "note": "survives restart",
            "ifVersion": None,
        }
    )
    assert put["ok"] is True, put

    durable = await (first.get("sessionPersistence") or first.get("session_persistence")).read_from(session.id, 0)
    assert any(
        event.get("type") == "assistant/message"
        and (event.get("data") or {}).get("message", {}).get("id") == fixture.assistant_message_ids[0]
        for event in durable.events
    )
    committed = put["value"]

    # The reference disposes the first composition's fiber before loading the
    # second one over the same roots.
    await first.fiber.dispose()

    second = await compose(root)
    await second.get("messageFeedback").ensure_initialized()
    listed = await second.get("messageFeedback").list({"sessionId": session.id})
    assert listed == {"ok": True, "value": {"items": [committed]}}
    assert second.get("sessions").get(session.id) is None
