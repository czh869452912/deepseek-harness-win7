"""Current Workspace snapshot-only persistence and fully qualified path gates."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from dsh.storage.hub import Storage
from dsh.workspace.current import CurrentWorkspacePlugin, realpath_normalize
from scripts.oracles.workspace_current_python import execute
from scripts.session_format_oracle import json_equal
from tests.test_session_agents_current import api_harness

CASES=json.loads((Path(__file__).resolve().parents[1]/'scripts/oracles/workspace_current_cases.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['case'])
def test_actual_source_workspace_registry_contract(case):
    assert json_equal(execute(case),case['expected'])


@pytest.mark.parametrize('path',['','relative','C:relative','\\rooted','/current-drive'])
def test_nonqualified_windows_paths_reject_before_filesystem_resolution(path):
    with patch('dsh.workspace.current.platform_of',return_value='win32'),patch('dsh.workspace.current.os.stat') as stat,patch('dsh.workspace.current.os.path.realpath') as resolver:
        with pytest.raises(TypeError,match='Workspace path is not fully qualified'):realpath_normalize(path)
        stat.assert_not_called()
        resolver.assert_not_called()


@pytest.mark.asyncio
async def test_actual_current_snapshot_bootstrap_refresh_and_reopen_without_event_opens(tmp_path):
    a,b=tmp_path/'a',tmp_path/'b';a.mkdir();b.mkdir()
    ctx,unused=await api_harness(tmp_path)
    Storage(ctx,root_dir=str(tmp_path/'storage'))
    async def create(sid,cwd):
        handle=await ctx.get('agents').create(dict(sessionId=sid,options=dict(provider='script',model='model'),meta=dict(cwd=str(cwd))))
        handle.agent.session.append('session/title',dict(title=sid,source='manual'))
        await handle.dispose()
    await create('one',a)
    persistence=ctx.get('sessionPersistence');real_open=persistence.open;opens=[]
    async def forbidden(*args,**kwargs):opens.append(args);raise AssertionError('workspace opened event body')
    persistence.open=forbidden
    try:
        fiber=await ctx.plugin(CurrentWorkspacePlugin);registry=ctx.get('workspaceRegistry')
        assert [row.sessionIds for row in registry.list()]==[['one']]
        assert registry.list()[0].title=='a'
        persistence.open=real_open
        await create('two',b)
        persistence.open=forbidden
        workspace=await registry.create(str(b))
        await workspace.attachSession('two')
        await registry.archiveSession('two')
        assert registry.archivedSessionIds==['two'] and workspace.sessionIds==['two']
        root=await registry.create(Path(str(a)).anchor)
        assert root.title==Path(str(a)).anchor
        await fiber.dispose();assert ctx.get('workspaceRegistry') is None
        await ctx.plugin(CurrentWorkspacePlugin)
        registry=ctx.get('workspaceRegistry')
        assert registry.archivedSessionIds==['two']
        assert (await registry.resolveByPath(str(b))).sessionIds==['two']
        assert not opens and not ctx.get('agents').list()
    finally:persistence.open=real_open;await ctx.fiber.dispose()
