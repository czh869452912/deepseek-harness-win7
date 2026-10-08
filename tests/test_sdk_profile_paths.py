import os
from pathlib import Path

from scripts.oracles.sdk_profile_driver import read_session_logs


def test_sdk_observer_reads_actual_long_session_path_without_changing_log_identity(tmp_path):
    home = tmp_path / ('sdk-home-' + 'a' * 160)
    physical = Path('\\\\?\\' + str(home)) if os.name == 'nt' else home
    log = physical / 'sessions' / ('project-' + 'b' * 60) / 'controlled' / 'session.jsonl'
    log.parent.mkdir(parents=True)
    payload = '{"text":"中文", "sequence": 1}\n'
    log.write_text(payload, encoding='utf-8')
    assert len(str(log)) > 260
    relative = log.relative_to(physical).as_posix()
    assert read_session_logs(home) == {relative: payload}
