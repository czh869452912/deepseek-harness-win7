import os
import shutil
import tempfile
import pytest
from dsh.guard.repeat_tool_reminder import RepeatToolReminderPlugin, GENTLE_REMINDER
from dsh.spill.spill_store import SpillStore


def test_repeat_tool_reminder_guard():
    plugin = RepeatToolReminderPlugin(config={"thresholds": [3, 5, 8]})
    session_id = "test-session"

    # Call 1 & 2: no reminder
    assert plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"}) is None
    assert plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"}) is None

    # Call 3: triggers gentle reminder
    rem3 = plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"})
    assert rem3 == GENTLE_REMINDER

    # Call 4: no reminder
    assert plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"}) is None

    # Call 5: triggers detailed reminder
    rem5 = plugin.record_and_check(session_id, "view", {"path": "/tmp/a.py"})
    assert "Repeated tool call detected:" in rem5
    assert "consecutive_calls: 5" in rem5


def test_spill_store():
    tmpdir = tempfile.mkdtemp()
    store = SpillStore(root=tmpdir)

    large_text = "A" * 100000
    spill_file = store.write_spill(large_text)
    assert os.path.exists(spill_file)

    recovered = store.read_spill(spill_file)
    assert recovered == large_text

    shutil.rmtree(tmpdir, ignore_errors=True)
