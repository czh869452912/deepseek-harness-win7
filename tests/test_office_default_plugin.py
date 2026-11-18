import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from dsh.office import plugin_current, runtime_inputs
from dsh.office.errors import OfficeKitError
from dsh.office.plugin_current import CurrentOfficeKitPlugin
from test_rc022_office_provider import Engine, source
from test_rc022_workspace_preview import setup


@pytest.mark.asyncio
async def test_injected_engine_keeps_provider_ownership_and_upstream_config(tmp_path, monkeypatch):
    ctx = await setup(tmp_path)
    engine = Engine()
    ctx.set_service('officeKitEngine', engine)
    def forbidden():
        raise AssertionError('Injected engine must not discover a second runtime.')
    monkeypatch.setattr(plugin_current, 'installed_runtime', forbidden)
    await ctx.plugin(CurrentOfficeKitPlugin, dict(outputDirectory=str(tmp_path / 'outputs')))
    try:
        assert (await ctx.officeKit.convert(source()))['pdf'].startswith(b'%PDF-')
        assert len(engine.created) == 1
    finally:
        await ctx.fiber.dispose()
    assert engine.closed == 1


@pytest.mark.asyncio
async def test_default_engine_is_lazy_and_retries_after_missing_runtime(tmp_path, monkeypatch):
    calls = []
    def unavailable():
        calls.append(1)
        raise FileNotFoundError('not prepared')
    monkeypatch.setattr(plugin_current, 'installed_runtime', unavailable)
    ctx = await setup(tmp_path)
    await ctx.plugin(CurrentOfficeKitPlugin, dict(outputDirectory=str(tmp_path / 'outputs')))
    try:
        assert not calls and ctx.get('officeKitEngine') is not None
        for index in range(2):
            with pytest.raises(OfficeKitError) as caught:
                await ctx.officeKit.convert(source(key='missing-' + str(index)))
            assert caught.value.code == 'unavailable' and 'LibreOffice Kit' in caught.value.message
        assert len(calls) == 2
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_actual_default_provider_converts_through_application_queue(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'LocalAppData'))
    executable = os.environ.get('DSH_TEST_OFFICE_BROWSER')
    root = Path(__file__).resolve().parents[1]
    original = root / 'reference'
    if not executable or not original.exists():
        pytest.skip('Explicit pinned original/browser inputs required.')
    package = original / 'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm'
    monkeypatch.setattr(plugin_current, 'installed_runtime', lambda: dict(executable=executable, package=str(package)))
    data = (original / 'packages/bundle/web-app/tests/fixtures/document-conversion.docx').read_bytes()
    ctx = await setup(tmp_path)
    await ctx.plugin(CurrentOfficeKitPlugin, dict(outputDirectory=str(tmp_path / 'outputs'),
                     fontDirectories=[str(Path(os.environ['WINDIR']) / 'Fonts' / name) for name in ('arial.ttf', 'arialbd.ttf', 'cour.ttf', 'times.ttf')]))
    try:
        result = await ctx.officeKit.convertTo(dict(source(data=data), format='txt', output=dict(owner='session', name='result.txt')))
        # Actual public SDK fixture observation (C9-BS); the lower-level Worker
        # probe supplies a different export operation and has its own receipt.
        assert Path(result['path']).read_bytes() == b'\xef\xbb\xbfOffice preview ready\r'
        assert result['missingFonts'] == ['Liberation Sans']
        cached = tmp_path / 'LocalAppData/libreoffice-kit/Cache/font-metadata.json'
        assert json.loads(cached.read_text(encoding='utf-8'))['format'] == 1
        owner = ctx.get('officeKitEngine')
        engine = owner.engine
        assert len(engine.converters) == 1
    finally:
        await ctx.fiber.dispose()
    assert not engine.converters and not engine.carrier.active and not engine.states


def inventory(tmp_path, monkeypatch):
    (tmp_path / 'browser').mkdir()
    (tmp_path / 'engine').mkdir()
    resources = {}
    for name, data in [('browser/chrome.exe', b'example binary'), ('engine/package.json', b'{}')]:
        (tmp_path / name).write_bytes(data)
        resources[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest = dict(format='dsh-office-runtime@1', architecture='x64', executable='browser/chrome.exe', package='engine', resources=resources)
    raw = json.dumps(manifest).encode('utf-8')
    (tmp_path / 'runtime.json').write_bytes(raw)
    monkeypatch.setattr(runtime_inputs, 'MANIFESTS', dict(x64=hashlib.sha256(raw).hexdigest()))
    return manifest


def test_runtime_inventory_checks_all_owned_bytes(tmp_path, monkeypatch):
    inventory(tmp_path, monkeypatch)
    assert runtime_inputs.verify_installed_runtime(tmp_path, 'x64') == dict(executable=str(tmp_path / 'browser/chrome.exe'), package=str(tmp_path / 'engine'))
    (tmp_path / 'browser/chrome.exe').write_bytes(b'altered')
    with pytest.raises(OfficeKitError, match='resource differs'):
        runtime_inputs.verify_installed_runtime(tmp_path, 'x64')


def test_unapproved_inventory_is_not_an_implicit_development_fallback(tmp_path, monkeypatch):
    inventory(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime_inputs, 'MANIFESTS', {})
    with pytest.raises(OfficeKitError, match='not approved'):
        runtime_inputs.verify_installed_runtime(tmp_path, 'x64')


@pytest.mark.parametrize('entry', ['../outside', '/absolute', 'C:/absolute', 'browser\\chrome.exe'])
def test_runtime_member_paths_cannot_escape_root(tmp_path, entry):
    with pytest.raises(ValueError, match='Invalid Office runtime'):
        runtime_inputs._plain_file(tmp_path, entry)
