import json

import pytest

from scripts import rc022_change_recorder_probe as corpus


@pytest.mark.asyncio
async def test_turn_recorder_keeps_snapshot_capture_and_disposal_contract(tmp_path):
    corpus.prepare(tmp_path)
    rows = await corpus.observe()
    (tmp_path/'recorder-observations.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    assert len(rows) == 12
    assert all(row['warnings'] == [] and row['scratchRemoved'] and row['untouched'] for row in rows)
    by_name = {row['name']: row for row in rows}
    assert by_name['no-tool-result']['events'] == []
    assert by_name['wrong-turn']['events'] == []
    assert by_name['outside-temporary-excluded']['events'] == []
    first = by_name['edit-once']
    assert len(first['events']) == 1
    assert first['snapshots'][0][0]['diffs'][0]['hunks'][0]['lines'] == ['-old', '+latest']
    assert by_name['empty-supersedes']['snapshots'][-1][-1]['summary']['files'] == []
    capped = by_name['list-cap-counts']['snapshots'][0][0]['summary']
    assert capped['total'] == 2 and capped['added'] == 3 and len(capped['files']) == 1
    assert capped['files'][0]['path'] == 'a'
    assert by_name['git-lazy-cap']['snapshots'][0][0]['diffs'][0]['kind'] == 'oversized'
    git = by_name['git-snapshot-and-ignored']['snapshots'][0][0]
    assert [file['path'] for file in git['summary']['files']] == ['ignored', 'tracked', 'uncaptured']
    assert len(by_name['next-turn-isolated']['events']) == 2
