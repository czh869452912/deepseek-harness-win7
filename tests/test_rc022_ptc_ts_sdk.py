import pytest

from dsh.core.ptc_sdk_ts import json_schema_to_ts, render_tools_sdk
from scripts.rc022_ptc_ts_sdk_probe import observe


@pytest.mark.asyncio
async def test_schema_and_all_program_format_projections():
    rows = await observe()
    assert all(isinstance(row['value'], str) and row['value'] for row in rows)
    examples = [row['value'] for row in rows if 'run_code({ code:' in row['value']]
    assert any('return await tools.bash' in text for text in examples)
    assert any('console.log(await tools.bash' in text for text in examples)
    assert all('*\\/' in text for text in examples)


def test_union_precedence_and_stack_safe_deep_schema():
    assert json_schema_to_ts(dict(type='array', items=dict(type='string', const='|&'))) == '("|&")[]'
    value = dict(type='string')
    for _ in range(1500):
        value = dict(type='array', items=value)
    assert json_schema_to_ts(value) == 'string' + '[]'*1500
    assert 'interface ToolArgsMap {}' in render_tools_sdk([])
