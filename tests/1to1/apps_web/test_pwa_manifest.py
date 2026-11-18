"""Current upstream PWA metadata and fixed-color favicon artifact contracts.

These static checks mirror the current metadata and SVG cases. Rasterizer and
maskable-pixel scenarios require actual Source/browser observations.
"""
import json
import os
import re
from typing import Any, Dict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DIST_ROOT = os.path.join(REPO_ROOT, "apps", "web", "dist")

EXPECTED_MANIFEST: Dict[str, Any] = {
    "name": "DeepSeek Harness",
    "short_name": "DSH",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "background_color": "#ffffff",
    "theme_color": "#ffffff",
    "icons": [
        {
            "src": "icon-192.png",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any",
        },
        {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_ships_install_metadata_with_the_built_web_application():
    """Mirrors upstream `it('ships install metadata with the built web application')`."""
    index = _read_text(os.path.join(DIST_ROOT, "index.html"))
    assert '<link rel="manifest" href="./manifest.webmanifest" />' in index
    assert '<link rel="apple-touch-icon" href="./apple-touch-icon.png" />' in index
    assert '<meta name="mobile-web-app-capable" content="yes" />' in index
    assert '<meta name="apple-mobile-web-app-title" content="DSH" />' in index

    manifest = json.loads(_read_text(os.path.join(DIST_ROOT, "manifest.webmanifest")))
    # Upstream asserts `expect(manifest).toEqual({...})`: JSON equality on the
    # whole document, not a subset check.
    assert manifest == EXPECTED_MANIFEST


def test_ships_a_favicon_that_switches_to_a_light_mark_under_dark_color_scheme():
    """Current Source selects two fixed-color SVGs through document media queries."""
    favicon = _read_text(os.path.join(DIST_ROOT, "favicon.svg"))
    dark = _read_text(os.path.join(DIST_ROOT, "favicon-dark.svg"))
    index = _read_text(os.path.join(DIST_ROOT, "index.html"))
    for icon, scheme in [('favicon.svg', 'light'), ('favicon-dark.svg', 'dark')]:
        assert '<link rel="icon" type="image/svg+xml" href="./%s" media="(prefers-color-scheme: %s)" />' % (icon, scheme) in index
    assert '<style>' not in favicon
    assert 'fill="#000"' in favicon
    assert 'fill="#fff"' in dark
    assert dark.replace('fill="#fff"', 'fill="#000"') == favicon
