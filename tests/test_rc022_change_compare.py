import json

import pytest

from scripts import rc022_change_compare_probe as corpus


@pytest.mark.asyncio
async def test_repeated_line_edits_reconstruct_files_with_exact_hunk_counts(tmp_path):
    rows = await corpus.observe()
    assert len(rows) == 1109
    for row in rows:
        before, after, result = row['case']['before'], row['case']['after'], row['result']
        # Preserve empty lines; only the single final terminator is ignored.
        def lines(value):
            if not value:
                return []
            return (value[:-1] if value.endswith('\n') else value).split('\n')
        old, expected = lines(before), lines(after)
        output, cursor = [], 0
        for hunk in result['hunks']:
            start = hunk['oldStart']-1
            output.extend(old[cursor:start])
            deleted = [line[1:] for line in hunk['lines'] if not line.startswith('+')]
            assert deleted == old[start:start+hunk['oldLines']]
            output.extend(line[1:] for line in hunk['lines'] if not line.startswith('-'))
            cursor = start+hunk['oldLines']
        output.extend(old[cursor:])
        assert output == expected
        assert result['added'] == sum(line.startswith('+') for hunk in result['hunks'] for line in hunk['lines'])
        assert result['deleted'] == sum(line.startswith('-') for hunk in result['hunks'] for line in hunk['lines'])
        if row['case']['timeoutMs'] < 0 and old != expected:
            assert result['coarse']
    (tmp_path/'change-compare-observations.json').write_text(json.dumps(rows, ensure_ascii=True), encoding='utf-8')
