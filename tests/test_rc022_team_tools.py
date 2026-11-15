import pytest
from scripts.rc022_team_tools_probe import observe


@pytest.mark.asyncio
async def test_actual_team_tool_pipeline_admission_names_and_cleanup(tmp_path):
    rows=await observe(tmp_path)
    metadata=rows[0]['data']
    assert len(metadata['tools'])==4
    assert sorted(tool['name'] for tool in metadata['tools'] if tool['concurrencySafe'])==['team_task_get','team_task_list']
    visibility=[row['names'] for row in rows if row.get('op')=='visible']
    expected=['team_task_create','team_task_get','team_task_list','team_task_update']
    assert visibility==[[],[],expected,expected,[],[],[]]
    prompts=[row['policy'] for row in rows if row.get('op')=='prompt']
    assert prompts==['',metadata['policy'],'','']
    successes=[row['value'] for row in rows if row.get('op')=='execute' and not row['isError']]
    assert successes[3]['owner']=='worker' and 'ownerId' not in successes[3]
    assert successes[5]['tasks'][0]['owner']=='worker'
    assert successes[7]['tasks'][0]['id']=='task-2' and 'nextCursor' not in successes[7]
    assert successes[8]['nextCursor']==2
    assert len([row for row in rows if row.get('op')=='execute' and row['isError']])==6
    held=next(row for row in rows if row.get('op')=='held-disable')
    assert held['isError'] and 'enable Agent Teams' in held['content'][0]['text']
    effects=rows[-1]
    assert not effects['inbox'] and len(effects['tasks'])==3
    assert 'no longer supported' in rows[-2]['error']
