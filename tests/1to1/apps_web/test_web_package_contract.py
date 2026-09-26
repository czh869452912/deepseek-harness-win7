"""
Supporting contract tests for `reference/apps/web/package.json`
(`@deepseek-ai/dsh-web-frontend`) and the vite build output it publishes.

These complement the official cases ported in ``test_pwa_manifest.py``: they
pin the package's *public contract* — the published subpath exports, the built
entry document, the preview page splice, and the build-time asset layout that
``reference/apps/web/vite.config.ts`` owns. The dist under ``apps/web/dist`` is
the upstream React 18 build and is what the Python SPA seat
(``dsh/host/frontend_static``) serves, so its shape is observable behavior of
this migration unit.

The source tree is mirrored verbatim from the pinned reference (``index.html``,
``src/main.ts`` with ``src/preview.ts`` and ``src/node-module-stub.ts``,
``vite.config.ts``, ``tsconfig.json``, ``tests/``, ``stress-tests/``); the built
``dist/`` ships with it because the Python 3.8.10 / Windows 7 runtime has no
Node build step. The source-to-dist derivation and the browser entry contract
are asserted in ``test_app_source_contract.py``.

Upstream sources of each asserted invariant:

  * ``package.json`` -> ``name`` / ``exports`` / ``files``.
  * ``vite.config.ts`` -> ``base: './'`` (relative asset URLs), the two build
    inputs (``index.html`` + ``src/preview.ts`` as the ``bootstrap`` entry),
    ``entryFileNames`` (``preview/`` for bootstrap, ``assets/`` otherwise),
    ``chunkFileNames`` (lazy ``@shikijs/langs`` grammars under
    ``assets/langs/``), ``assetFileNames`` (fonts under ``assets/fonts/``),
    ``sourcemap: true``, the ``worker.rollupOptions`` preview route, and
    ``emitPreviewPage()`` (``dist/preview.html`` is the built index page with
    one module script — the bootstrap entry — spliced ahead of its entry tag).
  * ``index.html`` + ``public/`` -> the document root element and the install
    metadata copied verbatim into ``dist/``.
"""

import json
import os
import re
from typing import List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WEB_ROOT = os.path.join(REPO_ROOT, "apps", "web")
DIST_ROOT = os.path.join(WEB_ROOT, "dist")
PUBLIC_ROOT = os.path.join(WEB_ROOT, "public")


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _tag_sources(html: str) -> List[str]:
    """Every module-script/stylesheet URL the built index page loads, in order."""
    urls = re.findall(r'<script[^>]*\bsrc="([^"]+)"', html)
    urls += re.findall(r'<link[^>]*\bhref="(\./[^"]+)"', html)
    return urls


def test_package_publishes_the_built_app_contract():
    package = json.loads(_read_text(os.path.join(WEB_ROOT, "package.json")))
    assert package["name"] == "@deepseek-ai/dsh-web-frontend"
    assert package["type"] == "module"
    # The published subpath surface: the dist payload plus the package metadata.
    assert package["exports"] == {
        "./dist/*": "./dist/*",
        "./package.json": "./package.json",
    }
    # Sourcemaps and the worker-preview surface are built but never published.
    assert package["files"] == [
        "dist",
        "!dist/**/*.map",
        "!dist/preview.html",
        "!dist/preview",
    ]
    # `.npmignore` drops sourcemaps from a directory publish of the same tree.
    assert _read_text(os.path.join(WEB_ROOT, ".npmignore")).strip() == "*.map"


def test_built_index_is_relative_and_declares_the_document_root():
    index = _read_text(os.path.join(DIST_ROOT, "index.html"))
    # `base: './'`: every emitted URL is relative, so the same payload mounts
    # under any base directory.
    urls = _tag_sources(index)
    assert urls, "built index.html carries no module entry"
    assert all(url.startswith("./") for url in urls)
    assert '<div id="root"></div>' in index
    assert "<title>DSH Local Build</title>" in index
    # Every emitted asset the page references exists in the published dist.
    for url in urls:
        assert os.path.isfile(os.path.join(DIST_ROOT, url[2:])), url


def test_built_asset_layout_groups_grammars_and_fonts():
    entry_dir = os.path.join(DIST_ROOT, "assets")
    langs_dir = os.path.join(entry_dir, "langs")
    fonts_dir = os.path.join(entry_dir, "fonts")
    assert any(name.endswith(".js") for name in os.listdir(entry_dir))
    assert any(name.endswith(".css") for name in os.listdir(entry_dir))
    # Lazy @shikijs/langs grammar chunks.
    assert any(name.endswith(".js") for name in os.listdir(langs_dir))
    # KaTeX faces referenced by the vendor stylesheet.
    assert any(name.endswith(".woff2") for name in os.listdir(fonts_dir))


def test_built_dist_carries_sourcemaps_and_the_preview_surface():
    """`sourcemap: true` emits the maps, and the preview surface owns `preview/`."""
    assets = os.path.join(DIST_ROOT, "assets")
    chunks = [name for name in os.listdir(assets) if name.endswith(".js")]
    assert chunks
    for name in chunks:
        assert os.path.isfile(os.path.join(assets, name + ".map")), name
    # The worker-preview surface: the bootstrap entry plus its worker chunk.
    preview = os.path.join(DIST_ROOT, "preview")
    assert len([name for name in os.listdir(preview)
                if name.startswith("bootstrap-") and name.endswith(".js")]) == 1
    assert any(name.startswith("worker-") and name.endswith(".js") for name in os.listdir(preview))
    assert os.path.isfile(os.path.join(DIST_ROOT, "preview.html"))


def test_preview_page_splices_the_bootstrap_entry_ahead_of_the_entry_tag():
    index = _read_text(os.path.join(DIST_ROOT, "index.html"))
    preview = _read_text(os.path.join(DIST_ROOT, "preview.html"))
    anchor = index.index('<script type="module"')
    # `preview/` holds the worker bootstrap plus the preview worker chunk; only
    # the `bootstrap` entry is spliced into the page.
    bootstrap_urls = [
        name
        for name in os.listdir(os.path.join(DIST_ROOT, "preview"))
        if name.endswith(".js") and name.startswith("bootstrap-")
    ]
    assert len(bootstrap_urls) == 1
    tag = '<script type="module" crossorigin src="./preview/%s"></script>' % bootstrap_urls[0]
    # Both pages share every chunk; the extra tag is the only difference.
    assert preview == index[:anchor] + tag + index[anchor:]


def test_public_assets_are_copied_verbatim_into_the_built_dist():
    for name in ("favicon.svg", "manifest.webmanifest"):
        source = _read_text(os.path.join(PUBLIC_ROOT, name)).replace("\r\n", "\n")
        built = _read_text(os.path.join(DIST_ROOT, name)).replace("\r\n", "\n")
        assert source == built, name
