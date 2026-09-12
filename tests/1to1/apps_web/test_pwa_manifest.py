"""
1:1 port of `reference/apps/web/tests/pwa-manifest.e2e.ts`
(`@deepseek-ai/dsh-web-frontend`).

Upstream cases (vitest, no browser — the file reads the vite build output):

  - ``ships install metadata with the built web application``
  - ``ships a favicon that switches to a light mark under dark color scheme``

Upstream reads ``new URL('../dist', import.meta.url)``, i.e. the built web
application the SPA seat serves. The Python port serves the same prebuilt dist
through ``dsh/host/frontend_static`` (``apps/web/dist/index.html``), so the
assertions read the identical artifact paths and the identical semantics:
exact manifest equality after JSON parsing, the exact manifest link tag in
``dist/index.html``, and the favicon's dark-scheme media query with both the
``#fff`` per-scheme fill and the black light-mode fill.

The install metadata is authored in ``apps/web/public/`` and copied verbatim
into ``dist/`` by the app build; ``test_web_package_contract.py`` asserts that
public -> dist relation. ``dist/index.html`` is the build of the mirrored
source document (``apps/web/index.html``), which declares the same manifest
link as a root-absolute URL; ``test_app_source_contract.py`` asserts that
source -> dist projection.
"""

import json
import os
import re
from typing import Any, Dict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DIST_ROOT = os.path.join(REPO_ROOT, "apps", "web", "dist")

EXPECTED_MANIFEST: Dict[str, Any] = {
    "id": "/",
    "name": "DeepSeek Harness",
    "short_name": "DSH",
    "start_url": "/",
    "scope": "/",
    "display": "fullscreen",
    "icons": [
        {
            "src": "/favicon.svg",
            "sizes": "any",
            "type": "image/svg+xml",
            "purpose": "any",
        }
    ],
}


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_ships_install_metadata_with_the_built_web_application():
    """Mirrors upstream `it('ships install metadata with the built web application')`."""
    index = _read_text(os.path.join(DIST_ROOT, "index.html"))
    assert '<link rel="manifest" href="./manifest.webmanifest" />' in index

    manifest = json.loads(_read_text(os.path.join(DIST_ROOT, "manifest.webmanifest")))
    # Upstream asserts `expect(manifest).toEqual({...})`: JSON equality on the
    # whole document, not a subset check.
    assert manifest == EXPECTED_MANIFEST


def test_ships_a_favicon_that_switches_to_a_light_mark_under_dark_color_scheme():
    """Mirrors upstream `it('ships a favicon that switches to a light mark ...')`."""
    favicon = _read_text(os.path.join(DIST_ROOT, "favicon.svg"))
    # The light fill must live inside the dark-scheme media query, so the icon
    # stays black in light mode and only turns white under a dark scheme.
    assert re.search(
        r"@media \(prefers-color-scheme: dark\)\s*{\s*path\s*{[^}]*fill:\s*#fff",
        favicon,
        re.IGNORECASE,
    ) is not None
    assert 'fill="#000"' in favicon
