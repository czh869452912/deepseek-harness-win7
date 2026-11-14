import asyncio
import copy
import json
from pathlib import Path
import pytest
from dsh.boot import prepare_profile_entries, prepare_profile_patches
from dsh.cordis import Context
from dsh.cordis.logger import Exporter
from scripts import rc022_preflight_probe as probe


def test_actual_profile_admission_and_import_side_effects(tmp_path):
    probe.OUTPUT = tmp_path
    rows = asyncio.run(probe.native())
    assert len(rows) == 34
    assert all(row['unchanged'] for row in rows)
    observed = {row['mode']:row for row in rows if 'mode' in row}
    assert all(not row['imported'] for row in observed.values())
    assert observed['basic']['rows'][1]['disabled'] is True
    assert 'disabled' not in observed['exempt']['rows'][1]
    assert observed['denied-group']['rows'][0]['group'] is False
    assert observed['include']['rows'][0]['disabled'] is True
    assert 'disabled' not in observed['include-patched']['rows'][0]
    assert 'disabled' not in observed['cycle']['rows'][0]
    assert observed['initial']['diagnostics']['include']
    assert observed['null']['diagnostics']['invalid']
    assert observed['malformed']['diagnostics']['invalid']
    assert observed['no-base']['error'] == 'Profile compatibility preflight requires a resolution base'
    assert observed['service']['rows'][0]['disabled'] is True
    assert observed['bad-record']['diagnostics']['record']
    for row in rows:
        if 'boot' not in row:
            continue
        assert row['effects']['denied'] == (['import:denied','apply:denied'] if row['boot']=='exempt' else [])
        assert row['effects']['allowed'] == ([] if row['boot']=='alias' else ['import:allowed','apply:allowed'])


@pytest.mark.asyncio
async def test_composed_profile_patches_are_detached_and_keep_full_override_order(tmp_path, capsys):
    ctx = Context(); ctx.provide('profileContext', {'dir':str(tmp_path)})
    patches = [{'insert':[{'id':'row','name':'cordis:builtin','config':{'value':1}}]},
        {'id':'row','config':{'value':2}}, {'id':'absent','disabled':True}]
    original = copy.deepcopy(patches)
    try:
        assert prepare_profile_patches(ctx, patches, tmp_path.as_uri()+'/') == [
            {'insert':[{'id':'row','name':'cordis:builtin','config':{'value':2}}]}]
        assert patches == original
        assert prepare_profile_patches(ctx, [], tmp_path.as_uri()+'/') == []
        assert prepare_profile_entries(ctx, [{'id':'off','name':'not-found','disabled':True}], tmp_path.as_uri()+'/') == [
            {'id':'off','name':'not-found','disabled':True}]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_literal_include_dialect_and_unmatched_patch_warnings(tmp_path):
    ctx = Context(); ctx.provide('profileContext', {'dir':str(tmp_path)})
    path = tmp_path/'nested.yml'
    path.write_text('- id: nested\n  name: cordis:builtin\n  disabled: !!js "false"\n',encoding='utf-8')
    rows = [{'id':'outer','name':'cordis:include','config':{'path':path.as_uri(), 'patches':[{'id':'absent','disabled':True}]}}]
    messages = []; ctx.logger.exporter(Exporter(lambda message:messages.append(str(message.args[0]))))
    try:
        assert prepare_profile_entries(ctx, rows, tmp_path.as_uri()+'/') == rows
        assert any('absent' in message for message in messages)
        assert path.read_text(encoding='utf-8').endswith('!!js "false"\n')
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_package_service_is_authoritative_and_unreadable_manifest_denies(tmp_path):
    ctx = Context(); ctx.provide('profileContext', {'dir':str(tmp_path)})
    package = tmp_path/'node_modules'/'local'; package.mkdir(parents=True)
    manifest = package/'package.json'; manifest.write_text('{"engines":{"dsh":"^99"}}',encoding='utf-8')
    class Packages:
        def packageOf(self, specifier, base): return None
    ctx.provide('pluginPackages', Packages())
    rows = [{'id':'row','name':'local'}]
    try:
        # No fallback to node_modules for a bare name when the package service is mounted.
        assert prepare_profile_entries(ctx, rows, tmp_path.as_uri()+'/') == rows
        module = package/'index.py'; module.write_text('raise Exception("never imported")',encoding='utf-8')
        manifest.unlink(); manifest.mkdir()
        checked = prepare_profile_entries(ctx, [{'id':'path','name':str(module)}], tmp_path.as_uri()+'/')
        assert checked[0]['disabled'] is True
    finally:
        await ctx.fiber.dispose()
