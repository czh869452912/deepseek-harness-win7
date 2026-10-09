import json
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


def test_real_browser_journey_observer_has_valid_module_syntax():
    node = shutil.which('node')
    assert node is not None
    result = subprocess.run([node, '--check', str(ROOT / 'scripts/oracles/browser_profiles/web_journey_browser.mjs')],
                            cwd=str(ROOT), capture_output=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
