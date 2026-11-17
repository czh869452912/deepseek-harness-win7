import json

import pytest

from scripts.rc022_cordis_inspect_tools_probe import observe,cases


@pytest.mark.asyncio
async def test_current_readonly_cordis_tools(tmp_path):
    rows=await observe()
    (tmp_path/'cordis-inspect-tools-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==21
    assert all(row['removed'] for row in rows)
    assert all(row['safe']==(row.get('error')!='args') for row in rows)
    assert rows[0]['value']['providers'][0]['id']=='fixture'
    assert any(row.get('error')=='Cordis inspection requires an Agent-backed session' for row in rows)
    assert rows[-1]['error']=='query failed'
    assert any(row['calls'] and row['calls'][0][3]=='<undefined>' for row in rows)
