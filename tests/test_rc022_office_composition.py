import json
from pathlib import Path

import pytest

from dsh.cordis import Context
from dsh.cordis.loader import evaluate_expr
from dsh.host.desktop.runtime import run_desktop_host
from scripts.rc022_workspace_tool_probe import payload


@pytest.mark.parametrize('value',[None,'','relative/runtime'])
def test_sdk_runtime_path_expression_uses_scoped_environment(tmp_path,monkeypatch,value):
    monkeypatch.chdir(tmp_path)
    ctx=Context();ctx.provide('nativeProcessEnvironment',{} if value is None else dict(DSH_PRIMARY_RUNTIME=value))
    expression="process.getBuiltinModule('node:path').resolve(process.env.DSH_PRIMARY_RUNTIME ?? '')"
    assert evaluate_expr(ctx,expression)==str((tmp_path/(value or '')).resolve())
    assert evaluate_expr(ctx,"!process.env.DSH_PRIMARY_RUNTIME")==(not value)
    assert evaluate_expr(ctx,"process.env.DSH_PRIMARY_RUNTIME ? 'workspace-dependencies' : 'user'")==('workspace-dependencies' if value else 'user')
    with pytest.raises(ValueError,match='Unsupported expression builtin'):evaluate_expr(ctx,"process.getBuiltinModule('node:child_process')")


@pytest.mark.asyncio
@pytest.mark.parametrize('bundled',[False,True])
async def test_actual_desktop_office_composition_environment_and_lazy_install(tmp_path,monkeypatch,bundled):
    monkeypatch.setenv('DSH_HOME',str(tmp_path/'home'));monkeypatch.setenv('DSH_TELEMETRY_DISABLED','1')
    source=tmp_path/'source';payload(source)
    monkeypatch.setenv('DSH_PRIMARY_RUNTIME',str(source) if bundled else '')
    runtime=await run_desktop_host(tmp_path/'profile')
    try:
        ctx=runtime.ctx
        assert ctx.get('officeKit') is not None
        names=[skill['name'] for skill in await ctx.skills.list()]
        assert all(name in names for name in ['office','office-docx','office-pptx','office-xlsx'])
        docx=await ctx.skills.get('office-docx')
        assert ('call `load_workspace_dependencies`' in docx['content'])==bundled
        installation=tmp_path/'home'/'dsh-runtimes'/'dsh-primary-runtime'
        assert not installation.exists()
        tool=ctx.tools.get('load_workspace_dependencies')
        if bundled:
            assert tool is not None
            value=await tool.handler({})
            assert Path(value['python']).is_file() and installation.is_dir()
            assert value['pythonDistributions']=={'Pillow':'10.4.0'}
        else:assert tool is None
    finally:await runtime.close()
