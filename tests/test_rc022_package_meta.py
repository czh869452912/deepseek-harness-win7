import builtins
import json
from pathlib import Path
import pytest
from dsh.boot import PluginPackages, readPluginMeta
from dsh.boot import package_meta
from dsh.cordis import Context
from scripts.rc022_resources_probe import fixture


def localized_fixture(root):
    table, parent = fixture(root, dict(mode='exports', value={
        '.':'./index.py','./locale/*.json':'./locale/*.json',
        './package.json':'./package.json','./icon':'./icon.svg'}))
    library = Path(table['entries'][0]['packageDir'])
    (library/'index.py').write_text('raise AssertionError("must not import")',encoding='utf-8')
    (library/'locale').mkdir()
    return table, parent, library


@pytest.mark.asyncio
async def test_metadata_is_read_only_fresh_and_falls_back_per_field(tmp_path):
    table, parent, library = localized_fixture(tmp_path)
    en = library/'locale/en.json'; zh = library/'locale/zh.json'
    en.write_text(json.dumps(dict(meta=dict(title='English'))),encoding='utf-8')
    zh.write_text(json.dumps(dict(meta=dict(description='介绍'))),encoding='utf-8')
    ctx = Context(); service = PluginPackages(ctx,dict(resolution=table))
    try:
        cached = service.packageOf('lib',parent)
        before = {str(p):p.read_bytes() for p in library.rglob('*') if p.is_file()}
        assert service.metaOf('lib',parent) == dict(title={'en':'English'},description={'en':'','zh':'介绍'})
        assert all(Path(p).read_bytes() == value for p,value in before.items())
        en.write_text(json.dumps(dict(meta=dict(title=' Updated '))),encoding='utf-8')
        assert service.metaOf('lib',parent)['title'] == {'en':' Updated '}
        assert service.packageOf('lib',parent) is cached
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_icon_growth_after_stat_keeps_text_and_does_not_fall_back(tmp_path,monkeypatch):
    table, parent, library = localized_fixture(tmp_path)
    manifest = library/'package.json'; value = json.loads(manifest.read_text(encoding='utf-8'))
    value['icon'] = './declared.png'; manifest.write_text(json.dumps(value),encoding='utf-8')
    icon = library/'declared.png'; icon.write_bytes(b'small')
    (library/'icon.svg').write_text('fallback',encoding='utf-8')
    def opening(path,mode='r',*args,**kwargs):
        if str(path) == str(icon) and mode == 'rb':
            with builtins.open(str(icon),'wb') as stream: stream.write(b'x'*(package_meta.MAX_ICON_BYTES+1))
        return builtins.open(path,mode,*args,**kwargs)
    monkeypatch.setattr(package_meta,'open',opening,raising=False)
    ctx = Context(); service = PluginPackages(ctx,dict(resolution=table))
    try:
        result = service.metaOf('lib',parent)
        assert result['title'] == 'lib'
        assert 'icon' not in result and 'icon exceeds 256 KiB' in result['error']
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_case_equivalent_locale_listing_is_rejected_on_windows(tmp_path,monkeypatch):
    table, parent, library = localized_fixture(tmp_path)
    (library/'locale/en.json').write_text('{"meta":{"title":"Title"}}',encoding='utf-8')
    listing = package_meta.os.listdir
    monkeypatch.setattr(package_meta.os,'listdir',lambda path:['en.json','EN.json'] if str(path)==str(library/'locale') else listing(path))
    ctx = Context(); service = PluginPackages(ctx,dict(resolution=table))
    try: assert 'duplicates locale en' in service.metaOf('lib',parent)['error']
    finally: await ctx.fiber.dispose()


def test_file_and_builtin_metadata_does_not_call_resolver(monkeypatch):
    def unexpected(*args): raise AssertionError('must not resolve non-package metadata')
    monkeypatch.setattr(package_meta,'resolve_plugin_resource',unexpected)
    for request in ('./file.py','../file.py','C:\\plugins\\entry.py','file:///entry.py','node:fs','fs','#alias','cordis:group'):
        assert readPluginMeta(request,'file:///caller.py') is None


@pytest.mark.asyncio
async def test_multilingual_resolution_bounds_manifest_reads_and_keeps_edits_fresh(tmp_path, monkeypatch):
    from dsh.boot import package_resolution
    table, parent, library = localized_fixture(tmp_path)
    for language in ('en', 'zh', 'fr', 'de', 'ja', 'ko', 'es', 'pt'):
        (library/('locale/'+language+'.json')).write_text(
            json.dumps(dict(meta=dict(title=language))), encoding='utf-8')
    (library/'icon.svg').write_text('<svg/>', encoding='utf-8')
    manifest = library/'package.json'
    reads = []
    original = package_resolution._read
    def reading(filename):
        reads.append(str(filename))
        return original(filename)
    monkeypatch.setattr(package_resolution, '_read', reading)
    ctx = Context(); service = PluginPackages(ctx, dict(resolution=table))
    try:
        first = service.metaOf('lib', parent)
        assert len(first['title']) == 8 and 'icon' in first
        assert reads.count(str(manifest)) == 1
        # The next call must re-resolve exports, not just refresh locale bytes.
        value = json.loads(manifest.read_text(encoding='utf-8'))
        value['exports']['./locale/*.json'] = None
        value['exports']['./icon'] = None
        manifest.write_text(json.dumps(value), encoding='utf-8')
        assert service.metaOf('lib', parent)['title'] == 'lib'
        assert reads.count(str(manifest)) == 2
        value['exports']['./locale/*.json'] = './locale/*.json'
        manifest.write_text(json.dumps(value), encoding='utf-8')
        (library/'locale/en.json').write_text('{', encoding='utf-8')
        assert 'error' in service.metaOf('lib', parent)
        (library/'locale/en.json').write_text('{"meta":{"title":"Recovered"}}', encoding='utf-8')
        assert service.metaOf('lib', parent)['title']['en'] == 'Recovered'
        # No resolution scope may leak through success or caught diagnostics.
        assert package_resolution._READS.get() is None
    finally:
        await ctx.fiber.dispose()
