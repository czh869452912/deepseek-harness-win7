"""
Source-tree contract for `reference/apps/web` (`@deepseek-ai/dsh-web-frontend`).

Upstream `apps/web` is a Vite application: `index.html` is the document, `src/main.ts`
the browser entry over the `@deepseek-ai/dsh-client-web` shell, `src/preview.ts` the
worker-preview bootstrap, and `vite.config.ts` the build that turns them into the
`dist/` payload this port's SPA seat (`dsh/host/frontend_static`) serves.

This port mirrors that source tree verbatim (the same convention the mirrored
`packages/**` trees follow) and ships the upstream-built `dist/` as the runtime
payload, because the Python 3.8.10 / Windows 7 runtime has no Node build step.
These cases therefore pin the mirrored source against the shipped artifact: what
`src/main.ts` boots, how the source document projects into the built document,
and which build rules the config declares. They are supporting contract tests —
the two official `apps/web` cases that need no toolchain are ported in
``test_pwa_manifest.py``; see ``test_vite_entry.py`` for the two that do.
"""

import os
import re
from typing import List

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WEB_ROOT = os.path.join(REPO_ROOT, "apps", "web")
SRC_ROOT = os.path.join(WEB_ROOT, "src")
DIST_ROOT = os.path.join(WEB_ROOT, "dist")
LANE_ROOT = os.path.join(WEB_ROOT, "tests")


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().replace("\r\n", "\n")


def _flat(text: str) -> str:
    """Collapse whitespace so multi-line source fragments match as one string."""
    return re.sub(r"\s+", " ", text).strip()


def test_source_document_projects_into_the_built_document():
    """`index.html` is the source of `dist/index.html`; `base: './'` rewrites its URLs."""
    source = _read_text(os.path.join(WEB_ROOT, "index.html"))
    built = _read_text(os.path.join(DIST_ROOT, "index.html"))

    # The mount point and document shell survive the build unchanged.
    assert '<div id="root"></div>' in source
    assert '<div id="root"></div>' in built
    assert "<title>DSH Local Build</title>" in source
    assert "<title>DeepSeek Harness</title>" in built
    config = _read_text(os.path.join(WEB_ROOT, "vite.config.ts"))
    assert "process.env.DSH_CLIENT_TITLE ?? DEFAULT_CLIENT_TITLE" in config
    assert "html.replace('<title>DSH Local Build</title>', `<title>${title}</title>`)" in config
    for line in ('<!doctype html>', '<html lang="en">', '<meta charset="utf-8" />',
                 '<meta name="viewport" content="width=device-width, initial-scale=1" />'):
        assert line in source, line
        assert line in built, line

    # The source document names its install metadata and entry as root-absolute
    # URLs; the built document carries the same two links under `base: './'`.
    assert '<link rel="manifest" href="/manifest.webmanifest" />' in source
    assert '<link rel="manifest" href="./manifest.webmanifest" />' in built
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />' in source
    assert '<link rel="icon" type="image/svg+xml" href="./favicon.svg" />' in built
    assert '<script type="module" src="/src/main.ts"></script>' in source

    # The built page drops the TypeScript entry in favour of the emitted chunk,
    # and every URL it carries is relative and present in the shipped dist.
    assert "/src/" not in built
    entry = re.search(r'<script type="module" crossorigin src="\./(assets/[^"]+\.js)"></script>', built)
    assert entry is not None, "built index.html carries no emitted entry chunk"
    assert os.path.isfile(os.path.join(DIST_ROOT, entry.group(1))), entry.group(1)
    for url in re.findall(r'(?:src|href)="(\./[^"]+)"', built):
        assert os.path.isfile(os.path.join(DIST_ROOT, url[2:])), url


def test_entry_module_boots_the_client_web_shell_from_the_root_element():
    """`src/main.ts` runs `AppWebEntry` from `@deepseek-ai/dsh-client-web`."""
    entry = _read_text(os.path.join(SRC_ROOT, "main.ts"))
    assert "import { AppWebEntry } from '@deepseek-ai/dsh-client-web'" in entry
    assert "document.getElementById('root')" in entry
    assert "throw new Error('web app: missing #root')" in entry
    assert "void new AppWebEntry(el).run()" in entry

    # The shipped payload is the build of that entry: the shell it mounts
    # carries its own boot contract, and none of the port-authored shell
    # identifiers the migrated app used before this source survived.
    shell = _built_scripts()
    assert "web app: missing #root" in shell
    assert "web boot: window.__ModuleLoader__ bootstrap facade is missing" in shell
    assert "did not activate" in shell
    assert "Failed to load plugins" in shell
    assert "Loading plugins" in shell
    for legacy in ("WebApplication", "SlotRegistry", "set_service"):
        assert legacy not in shell, legacy


def test_preview_bootstrap_selects_the_worker_source_before_connecting():
    """`src/preview.ts` is the one module `preview.html` adds ahead of the entry."""
    preview = _read_text(os.path.join(SRC_ROOT, "preview.ts"))
    assert "import DshWorker from '@deepseek-ai/dsh-experimental-webworker-runtime/worker?worker'" in preview
    assert "chooseWorkerHostSource, connectWorkerHost, IMAGE_FILE_NAME," in preview
    assert "from '@deepseek-ai/dsh-experimental-webworker-runtime/client'" in preview
    assert "const image = `preview/${IMAGE_FILE_NAME}`" in preview
    assert "const source = await chooseWorkerHostSource({ image })" in preview
    assert "await connectWorkerHost(new DshWorker({ name: 'dsh-host' }), { image, overlays: source.overlays })" in preview

    # The config registers it as its own build input so the shared page chunks
    # stay bootstrap-free, and routes both it and the preview worker to preview/.
    config = _flat(_read_text(os.path.join(WEB_ROOT, "vite.config.ts")))
    assert "bootstrap: src('./src/preview.ts')" in config
    assert "return chunk.name === 'bootstrap' ? 'preview/[name]-[hash].js' : 'assets/[name]-[hash].js'" in config
    assert "rollupOptions: { output: { entryFileNames: 'preview/[name]-[hash].js' } }" in config


def test_vite_config_declares_the_build_contract_of_the_shipped_dist():
    """The build rules `apps/web/vite.config.ts` declares, as `dist/` shows them."""
    config = _flat(_read_text(os.path.join(WEB_ROOT, "vite.config.ts")))

    # Relative asset URLs for both pages, and the worker-bootstrap target that
    # the top-level `await` in preview.ts requires.
    assert "base: './'" in config
    assert "target: 'es2022'" in config
    assert "sourcemap: true" in config
    assert "index: src('./index.html')" in config

    # Output layout: grammars under assets/langs/, fonts under assets/fonts/.
    assert "if (chunk.name === 'index' || chunk.name === 'vendor') return 'assets/[name]-[hash].js'" in config
    assert "chunk.moduleIds.some(id => id.includes('/node_modules/@shikijs/langs/'))" in config
    assert "const isFont = FONT_EXTENSIONS.some(ext => fileName.endsWith(ext))" in config
    assert "return isFont ? 'assets/fonts/[name]-[hash][extname]' : 'assets/[name]-[hash][extname]'" in config

    # One React identity for the shell, and the browser stand-in for the
    # vendored loader's only Node import.
    assert "dedupe: ['react', 'react-dom']" in config
    assert "{ find: /^node:module$/, replacement: src('./src/node-module-stub.ts') }" in config
    stub = _read_text(os.path.join(SRC_ROOT, "node-module-stub.ts"))
    assert "throw new Error('node:module is not available in the browser')" in stub

    # The build-time browser environment: `fromInternal()` probes the Node major
    # and takes neither branch, `envData` falls to its default.
    assert "clientBuildEnvironmentDefines(process.env)" in config
    assert "'process.versions.node': '\"0.0.0\"'" in config
    assert "'process.execArgv': '[]'" in config
    assert "'process.env.CORDIS_SHARED': 'undefined'" in config


def test_official_lane_and_stress_suite_are_mirrored():
    """The official `apps/web` test lane and its fixtures ship with the package."""
    for name in ("README.md", "README.zh.md", "pwa-manifest.e2e.ts", "vite-entry.e2e.ts",
                 "scaffold.ts", "support.ts", "assembled-boot.ts", "chat-scroll-fixture.ts",
                 "message-feedback-protocol.snapshot.ts", "minimal-preset.snapshot.ts",
                 "complex-history.perf.ts"):
        assert os.path.isfile(os.path.join(LANE_ROOT, name)), name
    assert os.path.isfile(os.path.join(LANE_ROOT, "support", "listen-probe.mjs"))
    assert os.path.isfile(os.path.join(WEB_ROOT, "stress-tests", "reasoning-chunks.stress.ts"))

    # The lane's owner-local goldens and snapshots.
    for golden in (os.path.join("expected", "web-runtime-context", "file-reference-prompt.expected.md"),
                   os.path.join("expected", "settings-chrome", "dialog.expected.md"),
                   os.path.join("snapshots", "preview-boot", "source-chooser.expected.md")):
        assert os.path.isfile(os.path.join(LANE_ROOT, golden)), golden

    # The lane boots the real composition in-process; it declares that in its README.
    readme = _read_text(os.path.join(LANE_ROOT, "README.md"))
    assert "boot the real web composition in-process and drive it with a real" in readme

    # Every `*.e2e.ts` file of the lane is mirrored, so no case lives only in reference/.
    reference_lane = os.path.join(REPO_ROOT, "reference", "apps", "web", "tests")
    if os.path.isdir(reference_lane):
        official = sorted(name for name in os.listdir(reference_lane) if name.endswith(".e2e.ts"))
        mirrored = sorted(name for name in os.listdir(LANE_ROOT) if name.endswith(".e2e.ts"))
        assert mirrored == official
        assert len(official) > 80


def test_shipped_dist_is_the_build_of_the_mirrored_source():
    """
    Every build input the source maps embed is the mirrored file itself.

    `vite.config.ts` builds with `sourcemap: true`, so each emitted chunk carries
    its inputs in `sourcesContent`. Comparing those bytes against the trees this
    port mirrors is what distinguishes 'the served payload is the upstream build
    of the pinned source' from 'the served payload looks similar': no string
    sniffing, and any port-local edit to a source the payload was built from
    fails here.
    """
    import json

    resolved = {}  # source path -> (map path, on-disk path)
    maps = []
    for dirpath, _dirnames, filenames in os.walk(DIST_ROOT):
        for name in filenames:
            if name.endswith(".js.map"):
                maps.append(os.path.join(dirpath, name))
    assert maps, "the shipped dist carries no source maps"

    for map_path in maps:
        with open(map_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        sources = document["sources"]
        contents = document["sourcesContent"]
        assert len(sources) == len(contents), map_path
        for source, embedded in zip(sources, contents):
            if "packages/" not in source and not re.search(r"(^|/)src/[\w.-]+\.(ts|js)$", source):
                continue
            if embedded is None:
                continue
            candidates = [
                os.path.normpath(os.path.join(os.path.dirname(map_path), source)),
                os.path.normpath(os.path.join(REPO_ROOT, source.lstrip("./"))),
            ]
            found = next((path for path in candidates if os.path.isfile(path)), None)
            if found is None:
                # The only build inputs this port does not carry are the vendored
                # and npm package trees; nothing else may go unverified.
                stripped = source.lstrip("./")
                assert stripped.startswith("node_modules/") or stripped.startswith("vendor/"), (map_path, source)
                continue
            assert embedded.replace("\r\n", "\n") == _read_text(found), (map_path, source)
            resolved[source] = found

    # The shell chunk is the build of the mirrored browser entry, the vendored
    # browser stand-in, and the four client packages it embeds inline.
    for source in ("../../src/main.ts", "../../src/node-module-stub.ts",
                   "../../../../packages/client/web/lib/index.js",
                   "../../../../packages/client/store/lib/index.js",
                   "../../../../packages/client/ui-slots/lib/index.js",
                   "../../../../packages/client/ui-primitives/lib/index.js"):
        assert source in resolved, source

    # The preview surface is the build of the mirrored worker bootstrap, the
    # worker entry, and its client half.
    for source in ("../../src/preview.ts",
                   "../../../../packages/experimental/webworker-runtime/lib/client.js",
                   "../../../packages/experimental/webworker-runtime/lib/worker.js"):
        assert source in resolved, source

    # The browser entry the built chunk embeds is read from the mirrored source:
    # the mount goes to `#root`, and the refusal is the packaged one.
    assert "web app: missing #root" in _read_text(resolved["../../src/main.ts"])


def _built_scripts() -> str:
    """Every emitted JS chunk of the shipped dist, concatenated."""
    assets = os.path.join(DIST_ROOT, "assets")
    parts: List[str] = []
    for name in sorted(os.listdir(assets)):
        if name.endswith(".js"):
            parts.append(_read_text(os.path.join(assets, name)))
    assert parts, "dist/assets carries no emitted chunk"
    return "\n".join(parts)
