import json
import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

from dsh.cordis.context import Context
from dsh.host.browser_compat.plugin import BrowserCompatibilityPlugin, SCRIPT
from dsh.host.webserver.webserver import WebServerService


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_host_owns_early_injection_and_unload_removes_it():
    ctx = Context()
    server = WebServerService(ctx)
    ctx.set_service('webServer', server)
    ctx.on('webserver/index-inject', lambda rows: rows.append(dict(kind='script', text='application()')))
    fiber = await ctx.plugin(BrowserCompatibilityPlugin)
    try:
        body = server.render_index('<html><head><script type="module" src="/entry.js"></script></head><body></body></html>')
        assert body.index(SCRIPT) < body.index('application()') < body.index('/entry.js')
        # A raw tap is applied after structured rows; the final guard must catch
        # an extension that removes or moves the adapter, not only raw index bytes.
        remove = server.tap_index(lambda html: '<script>tooEarly()</script>' + html)
        with pytest.raises(RuntimeError, match='before all'):
            server.render_index('<head></head><body></body>')
        remove()
        await fiber.dispose()
        assert ctx.get('browserCompatibility') is None
        assert SCRIPT not in server.render_index('<head></head><body></body>')
    finally:
        await ctx.fiber.dispose()


@pytest.mark.parametrize('policy', ["script-src 'self'", "default-src 'none'", "script-src-elem 'self'",
                                  "script-src 'unsafe-inline' 'nonce-other'"])
def test_csp_that_blocks_adapter_is_rejected(policy):
    with pytest.raises(RuntimeError, match='CSP'):
        BrowserCompatibilityPlugin().validate_index('<head><meta http-equiv="Content-Security-Policy" content="' +
            policy + '"><script>' + SCRIPT + '</script></head>')


def test_independent_realm_capabilities_and_native_preservation():
    node = shutil.which('node')
    assert node is not None, 'capability semantics requires the development Node runtime'
    result = subprocess.run([node, str(ROOT / 'scripts/browser_compat_semantics.mjs')],
                            cwd=str(ROOT), capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['passed']


@pytest.mark.parametrize('name', ['web_journey_browser.mjs', 'rc3_document_journey.mjs', 'rc3_application_journey.mjs'])
def test_real_browser_journey_observer_has_valid_module_syntax(name):
    node = shutil.which('node')
    assert node is not None
    result = subprocess.run([node, '--check', str(ROOT / 'scripts/oracles/browser_profiles' / name)],
                            cwd=str(ROOT), capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_worker_adapter_owns_only_recognized_workers_and_releases_resources():
    result = subprocess.run([shutil.which('node'), str(ROOT / 'scripts/browser_worker_semantics.mjs')],
                            cwd=str(ROOT), capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['passed']


def test_source_and_python_inject_identical_composed_adapter():
    expression = ('import {browserCompatibilityInput} from "./scripts/browser_compat_input.mjs";'
                  'console.log((await browserCompatibilityInput("dsh/host/browser_compat")).sha256);')
    result = subprocess.run([shutil.which('node'), '--input-type=module', '-e', expression],
                            cwd=str(ROOT), capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == hashlib.sha256(SCRIPT.encode('utf-8')).hexdigest()


def test_url_adapter_has_recorded_bytes_license_and_reviewed_entry():
    directory = ROOT / 'dsh/host/browser_compat'
    record = json.loads((directory / 'url-input.json').read_text(encoding='utf-8'))
    assert record['package'] == 'core-js' and record['version'] == '3.49.0'
    assert record['license'] == 'MIT'
    data = (directory / 'url.js').read_bytes()
    assert record['output'] == dict(path='url.js', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    assert hashlib.sha256((directory / 'url.LICENSE.txt').read_bytes()).hexdigest() == record['licenseSha256']
    entry = (directory / 'url-entry.cjs').read_text(encoding='utf-8').encode('utf-8')
    assert next(row for row in record['inputs'] if row['path'] == 'url-entry.cjs')['sha256'] == hashlib.sha256(entry).hexdigest()
    assert data.decode('utf-8') + '\n' in SCRIPT


def test_url_adapter_builder_requires_explicit_inputs(tmp_path):
    node = shutil.which('node')
    result = subprocess.run([node, str(ROOT / 'scripts/build_browser_url_adapter.mjs')],
                            cwd=str(tmp_path), capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode != 0
    assert 'Explicit core-js package and esbuild package paths required' in result.stderr


def test_url_adapter_builder_rejects_wrong_source_version(tmp_path):
    package = tmp_path / 'source'
    package.mkdir()
    (package / 'package.json').write_text(json.dumps(dict(name='core-js', version='0.0.0')), encoding='utf-8')
    builder = tmp_path / 'builder.cjs'
    builder.write_text('module.exports = {version:"0.25.12"};', encoding='utf-8')
    result = subprocess.run([shutil.which('node'), str(ROOT / 'scripts/build_browser_url_adapter.mjs'),
                             '--source', str(package), '--esbuild', str(builder)],
                            cwd=str(tmp_path), capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode != 0 and '0.0.0' in result.stderr


def test_anchor_adapter_has_pinned_bytes_and_all_dependency_licenses():
    directory = ROOT / 'dsh/host/browser_compat'
    record = json.loads((directory / 'anchor-input.json').read_text(encoding='utf-8'))
    assert record['package'] == '@oddbird/css-anchor-positioning'
    assert record['version'] == '0.10.2' and record['license'] == 'BSD-3-Clause'
    data = (directory / 'anchor.js').read_bytes()
    assert record['output'] == dict(path='anchor.js', bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    assert hashlib.sha256((directory / 'anchor.LICENSE.txt').read_bytes()).hexdigest() == record['licenseSha256']
    assert hashlib.sha256((directory / 'anchor.third-party-LICENSE.txt').read_bytes()).hexdigest() == record['thirdPartyLicenseSha256']
    assert {row['package'] for row in record['thirdPartyLicenses']} == {
        '@floating-ui/dom', '@floating-ui/utils', 'css-tree', 'nanoid'}
    assert data.decode('utf-8') in SCRIPT
