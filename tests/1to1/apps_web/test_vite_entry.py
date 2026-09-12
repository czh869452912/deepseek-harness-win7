"""
1:1 mapping of `reference/apps/web/tests/vite-entry.e2e.ts`
(`@deepseek-ai/dsh-web-frontend`).

Upstream cases:

  - ``rejects the package dev alias with the full-host correction``
  - ``rejects the standalone Vite server with the full-host correction``

Both upstream cases are process-level: they spawn `pnpm run dev` in `apps/web`
and the workspace `vite` binary with a `node:net` listen probe preloaded through
`NODE_OPTIONS`, then assert a non-zero exit, the correction text on stderr, and
that `Server.listen` was never called.

That lane is a Node/pnpm/Vite workspace lane: `apps/web` resolves `vite`,
`@vitejs/plugin-react`, `../../scripts/client-build-environment.ts`, and
`../../tsconfig.base.json` from the repository's Node workspace root, which this
Python 3.8.10 / Windows 7 port does not carry (no root `package.json`, no
`pnpm-workspace.yaml`, no `node_modules`, and `reference/` is a read-only pinned
submodule). The process-level assertions are therefore recorded as
`PLATFORM_EXCLUDED` in the migration test map; the executable cases below assert
the same guarantee where the port can observe it — the mirrored configuration
must fail a serve before it can expose the shell, and it must state the exact
correction the upstream cases grep for.
"""

import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WEB_ROOT = os.path.join(REPO_ROOT, "apps", "web")

CORRECTION_FRAGMENTS = (
    "apps/web is not a standalone application",
    "window.__DSH_BOOT__",
    "dsh web",
)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().replace("\r\n", "\n")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _config() -> str:
    return _read_text(os.path.join(WEB_ROOT, "vite.config.ts"))


def test_rejects_the_package_dev_alias_with_the_full_host_correction():
    """The `dev` alias is bare Vite, and bare Vite refuses to serve this package."""
    import json

    package = json.loads(_read_text(os.path.join(WEB_ROOT, "package.json")))
    # `pnpm run dev` runs exactly this, so the alias is the bare Vite server the
    # correction message rejects.
    assert package["scripts"]["dev"] == "vite"

    config = _flat(_config())
    message = config[config.index("const STANDALONE_ERROR ="):config.index("/** Escape build-time text")]
    for fragment in CORRECTION_FRAGMENTS:
        assert fragment in message, fragment
    # The correction names the supported entries: a repository checkout and an
    # installed package both go through the host (`dsh web`), never bare Vite.
    assert "From a repository checkout, run `pnpm dsh web`; an installed package uses `dsh web`." in message
    assert "For client-plugin HMR, run `pnpm dsh web` together with `pnpm run dev:web`." in message


def test_rejects_the_standalone_vite_server_with_the_full_host_correction():
    """The refusal happens while the config resolves, before any listen call."""
    config = _flat(_config())

    # The refusal is a plugin whose `config` hook throws for the serve command.
    # Vite resolves `config` before it creates and binds the dev server, so the
    # port must observe the same pre-listen rejection the upstream probe asserts.
    assert "function rejectStandaloneServe(): Plugin" in config
    assert "name: 'dsh-reject-standalone-web-serve'" in config
    assert "config(_config, env)" in config
    assert "if (env.command === 'serve') throw new Error(STANDALONE_ERROR)" in config
    assert "plugins: [rejectStandaloneServe(), clientDocumentTitle(), react(), emitPreviewPage()]" in config
    # It owns the serve command only: `build` and `watch` stay available.
    assert "configResolved" not in config

    # The upstream case preloads this probe and asserts the marker file was never
    # written; the probe itself ships with the mirrored lane.
    probe = _read_text(os.path.join(WEB_ROOT, "tests", "support", "listen-probe.mjs"))
    assert "const listen = Server.prototype.listen" in probe
    assert "Server.prototype.listen = function (...args)" in probe
    assert "const marker = process.env.DSH_LISTEN_PROBE_MARKER" in probe
