import pytest
from scripts.rc022_executor_selection_probe import observe


@pytest.mark.asyncio
async def test_executor_lifetime_scope_and_prompt_selection():
    rows={row['action']:row for row in await observe()}
    unavailable=dict(code='TOOL_EXECUTOR_UNAVAILABLE')
    for key in ('missing','root-unload','scoped-unload','accepted'):
        assert rows[key]['dispatch']==unavailable
    assert rows['accepted']['accepted']==dict(provider='root',same=True)
    assert rows['accepted']['during']==unavailable
    assert rows['scoped-replace']['unloaded']==unavailable
    assert rows['scoped-replace']['dispatch']==dict(provider='replacement',same=True)
    assert rows['inherited']['dispatch']==dict(provider='local',same=False)
    assert rows['duplicate']['duplicate']=='Only one tool executor may be registered in each scope'
    assert rows['sections']['schemas']==['local']
    assert rows['sections']['sections']==[dict(name='fixture-local',text='local:'),dict(name='fixture-root',text='')]
    assert rows['register-rollback']==dict(action='register-rollback',error='change failed',leaked=False,retry=True)
    assert rows['register-nesting']==dict(action='register-nesting',trace=[True,'last'],remaining=False)


@pytest.mark.parametrize('key', ['mode','maxParallelSubCalls'])
def test_candidate_rejects_removed_configuration(key):
    from dsh.cordis import Context
    from dsh.core.tools import ToolsService
    with pytest.raises(ValueError,match='removed'):
        ToolsService(Context(),{key:'native'},contract_version=4)
