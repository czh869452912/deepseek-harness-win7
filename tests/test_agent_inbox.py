import pytest
from dsh.cordis.context import Context
from dsh.core.inbox import Inbox


def test_inbox_queue_operations_and_events():
    ctx = Context()
    events_log = []

    ctx.on("agent/inbox/inserted", lambda p: events_log.append(("inserted", p["target"], p["message"]["content"])))
    ctx.on("agent/inbox/claimed", lambda p: events_log.append(("claimed", p["message"]["content"])))
    ctx.on("agent/inbox/discarded", lambda p: events_log.append(("discarded", p["message"]["content"])))

    inbox = Inbox(ctx=ctx)

    # 1. Append to next-turn
    id1 = inbox.append("next-turn", {"content": "Turn 1 prompt"})
    # 2. Append to next-step (steering)
    id2 = inbox.append("next-step", {"content": "Step 1 steering"})

    assert len(inbox.next_turn) == 1
    assert len(inbox.next_step) == 1

    # 3. Replace a message
    inbox.replace(id1, {"id": id1, "content": "Updated Turn 1 prompt"})
    assert inbox.next_turn[0]["content"] == "Updated Turn 1 prompt"

    # 4. Claim: next-turn claims all next_step items + head of next_turn
    claimed = inbox.claim(target="next-turn")
    assert len(claimed) == 2
    assert claimed[0]["content"] == "Step 1 steering"
    assert claimed[1]["content"] == "Updated Turn 1 prompt"
    assert inbox.is_empty() is True

    # 5. Prepend and remove
    id3 = inbox.prepend("next-turn", {"content": "Turn 2 prompt"})
    assert len(inbox.next_turn) == 1
    inbox.remove(id3)
    assert len(inbox.next_turn) == 0

    # Verify event counts
    inserted_count = sum(1 for e in events_log if e[0] == "inserted")
    claimed_count = sum(1 for e in events_log if e[0] == "claimed")
    discarded_count = sum(1 for e in events_log if e[0] == "discarded")

    assert inserted_count >= 3
    assert claimed_count == 2
    assert discarded_count >= 2
