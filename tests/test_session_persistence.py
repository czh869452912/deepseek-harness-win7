import os
import shutil
import tempfile
import pytest
from dsh.core.session import SessionHeader
from dsh.session.persistence_jsonl import JsonlSessionPersistence


@pytest.fixture
def temp_session_dir():
    tmp = tempfile.mkdtemp(prefix="dsh_session_test_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_session_create_and_append(temp_session_dir):
    persistence = JsonlSessionPersistence(root=temp_session_dir)

    header = SessionHeader(session_id="test-session-1", cwd=temp_session_dir)
    await persistence.create(header)

    loc = persistence.locate(header)
    assert not os.path.exists(loc.path)

    events = [
        {"time": 1, "seq": 0, "type": "turn/start", "data": {"turn": 1}},
        {"time": 1, "seq": 1, "type": "user/message", "surfaceOp": "append", "data": {"id": "u1", "role": "user", "source": {"kind": "user"}, "content": [{"type": "text", "text": "Hello"}]}},
        {"time": 1, "seq": 2, "type": "turn/end", "data": {"turn": 1, "reason": {"kind": "completed"}}},
    ]

    await persistence.append("test-session-1", events)

    inspection = await persistence.load("test-session-1")
    assert inspection.meta.id == "test-session-1"
    assert len(inspection.events) == 3
    assert inspection.events[1]["data"]["content"][0]["text"] == "Hello"


@pytest.mark.asyncio
async def test_session_packed_chunks(temp_session_dir):
    persistence = JsonlSessionPersistence(root=temp_session_dir, pack_chunks=True)

    header = SessionHeader(session_id="test-session-packed", cwd=temp_session_dir)
    await persistence.create(header)

    await persistence._create(header)  # Physical backend fixture, not public lazy create.

    # Write a packed text-chunks row directly into the file to test unpack
    path = persistence.locate(header).path
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"type": "text-chunks", "seq0": 0, "time0": 1000, "data": {"turn": 1, "step": 1, "index": 0, "dt": [50], "texts": ["H", "i"]}}\n')

    inspection = await persistence.load("test-session-packed")
    assert len(inspection.events) == 2
    assert inspection.events[0]["type"] == "assistant/chunk"
    assert inspection.events[0]["seq"] == 0
    assert inspection.events[0]["data"]["chunk"]["text"] == "H"
    assert inspection.events[1]["type"] == "assistant/chunk"
    assert inspection.events[1]["seq"] == 1
    assert inspection.events[1]["data"]["chunk"]["text"] == "i"


@pytest.mark.asyncio
async def test_session_crash_recovery(temp_session_dir):
    persistence = JsonlSessionPersistence(root=temp_session_dir)

    header = SessionHeader(session_id="test-crashed-session", cwd=temp_session_dir)
    await persistence.create(header)

    # An interrupted turn (turn/start without turn/end)
    events = [
        {"time": 1, "seq": 0, "type": "turn/start", "data": {"turn": 1}},
        {"time": 1, "seq": 1, "type": "user/message", "surfaceOp": "append", "data": {"id": "u1", "role": "user", "source": {"kind": "user"}, "content": [{"type": "text", "text": "Do task"}]}},
        {"time": 1, "seq": 2, "type": "step/start", "data": {"turn": 1, "step": 1}},
    ]
    await persistence.append("test-crashed-session", events)

    # Pinned repair.spec.ts closes both the open step and its turn.
    inspect_result = await persistence.inspect("test-crashed-session")
    assert [e["type"] for e in inspect_result.events[-2:]] == ["step/end", "turn/end"]
    assert len(inspect_result.events) == 5
    assert inspect_result.events[-1]["data"]["reason"]["kind"] == "interrupted"
    assert len((await persistence.read_from("test-crashed-session", 0)).events) == 3

    load_result = await persistence.load("test-crashed-session")
    assert load_result.events == inspect_result.events
    assert (await persistence.read_from("test-crashed-session", 0)).events == load_result.events
    assert (await persistence.load("test-crashed-session")).events == load_result.events


@pytest.mark.asyncio
async def test_session_list_and_snapshots(temp_session_dir):
    persistence = JsonlSessionPersistence(root=temp_session_dir)

    h1 = SessionHeader(session_id="session-a", cwd=temp_session_dir)
    h2 = SessionHeader(session_id="session-b", cwd=temp_session_dir)

    await persistence.create(h1)
    await persistence.create(h2)

    assert await persistence.list() == []
    await persistence.append(h1.id, [{"type": "session/end-seed", "seq": 0, "time": 1, "data": {}}])
    await persistence.append(h2.id, [{"type": "session/end-seed", "seq": 0, "time": 1, "data": {}}])
    headers = await persistence.list()
    ids = [h.id for h in headers]
    assert "session-a" in ids
    assert "session-b" in ids

    snapshots = await persistence.list_snapshots()
    assert len(snapshots) == 2
    assert all(s.revision is not None for s in snapshots)
