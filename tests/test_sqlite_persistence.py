import os
import pytest
import tempfile
from dsh.session.persistence_sqlite import SqliteSessionPersistence
from dsh.core.session import SessionHeader


@pytest.mark.asyncio
async def test_sqlite_session_persistence_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        persistence = SqliteSessionPersistence(db_path=db_path)

        try:
            header = SessionHeader(session_id="sqlite-session-1", cwd=tmpdir)
            await persistence.create(header)

            events = [
                {"seq": 0, "type": "turn/start", "time": 1000, "data": {"turn": 1}},
                {"seq": 1, "type": "user/message", "time": 1010, "data": {"content": "Hello SQL"}},
                {"seq": 2, "type": "turn/end", "time": 1020, "data": {"turn": 1, "reason": {"kind": "completed"}}},
            ]
            await persistence.append("sqlite-session-1", events)

            inspection = await persistence.load("sqlite-session-1")
            assert inspection.meta.id == "sqlite-session-1"
            assert len(inspection.events) == 3
            assert inspection.events[1]["data"]["content"] == "Hello SQL"

            snapshots = await persistence.list_snapshots()
            assert len(snapshots) == 1
            assert snapshots[0].header.id == "sqlite-session-1"
        finally:
            persistence.close()
