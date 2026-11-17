import json

import pytest

from dsh.host.workspace_runtime_manifest_current import parsePrimaryRuntime,workspaceDependencyPaths
from scripts.rc022_workspace_manifest_probe import observe,cases,manifest


@pytest.mark.asyncio
async def test_runtime_manifest_and_entry_paths_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'workspace-manifest-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==len(cases())==334
    assert rows[0]['value']==manifest()
    assert any(row.get('error')=='primary runtime: conflicting numpy distribution version' for row in rows)
    assert rows[-4]['value']['pythonPackages']=={} and 'components' not in rows[-4]['value']
    assert all(row==dict(error='primary runtime: invalid metadata') for row in rows[-3:])


def test_selected_distribution_map_ownership_and_windows_python_layout():
    value=manifest();parsed=parsePrimaryRuntime(value)
    assert parsed['pythonPackages'] is value['pythonPackages']
    paths=workspaceDependencyPaths('C:\\runtime',parsed)
    assert paths['pythonDistributions'] is value['pythonPackages']
    assert paths['python'].endswith('python.exe')
    assert 'node' not in paths and 'pnpm' not in paths and 'nodePackages' not in paths
    assert paths['pythonPackages'].replace('\\','/').endswith('/python/Lib/site-packages')
