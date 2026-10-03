from pathlib import Path

import pytest

from scripts.acp_permission_journey import journey

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mode', ['allow', 'reject', 'malformed', 'cancel-late', 'close-late', 'eof'])
def test_actual_permission_process_keeps_one_shot_tool_and_shutdown_ownership(tmp_path, mode):
    result = journey(ROOT, tmp_path, [mode])
    assert result['modes'] == [mode] and result['processes'] == 1
    assert result['observations'][0]['executed'] is (mode == 'allow')
