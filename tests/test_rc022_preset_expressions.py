from pathlib import Path
import json

import pytest

from dsh.cordis import Context
from dsh.cordis.loader import evaluate_expr
from dsh.boot.plugin_packages import PluginPackages
from dsh.boot.runtime_resolution import create_runtime_resolution
from scripts.rc022_preset_expression_probe import EXPRESSION,prepare,observe


@pytest.mark.asyncio
async def test_official_preset_path_and_require_expressions(tmp_path):
    prepare(tmp_path);rows=await observe(tmp_path/'files')
    (tmp_path/'preset-expression-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    assert len(rows)==8
    assert rows[0]['value']==str(tmp_path/'files/node_modules/fixture-preset/skills')
    assert rows[4]['value'].endswith('require.json')
    assert rows[5:]==[dict(code='ERR_PACKAGE_PATH_NOT_EXPORTED'),dict(code='MODULE_NOT_FOUND'),dict(value='node:path')]


@pytest.mark.asyncio
async def test_preset_expression_resolves_installation_package_from_profile(tmp_path):
    installation=tmp_path/'installation';package=installation/'node_modules/fixture-preset';package.mkdir(parents=True)
    manifest=dict(name='fixture-preset',exports={'./package.json':'./package.json'})
    (package/'package.json').write_text(json.dumps(manifest),encoding='utf-8')
    anchor=installation/'package.json';anchor.write_text(json.dumps(dict(name='installation',dependencies={'fixture-preset':'*'})),encoding='utf-8')
    home=tmp_path/'home';profile=home/'profiles/web';profile.mkdir(parents=True)
    resolution=await create_runtime_resolution(dict(installAnchor=str(anchor),home=str(home)))
    ctx=Context();ctx.baseUrl=profile.as_uri()+'/'
    try:
        PluginPackages(ctx,dict(resolution=resolution))
        assert evaluate_expr(ctx,EXPRESSION)==str(package/'skills')
    finally:await ctx.fiber.dispose()
