"""
Client Modules Registry (`@deepseek-ai/dsh-client-modules`).
Scans packages declaring `dsh.client`, composes the `window.__DSH_BOOT__` graph,
serves `/plugins/<id>/client.js` bundle endpoints, and taps index.html responses.
"""

import hashlib
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote

from dsh.cordis.plugin import Plugin
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService


def short_hash(data: bytes) -> str:
    """Compute sha1 hash shortened to 12 hex characters."""
    return hashlib.sha1(data).hexdigest()[:12]


def order_by_module_graph(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Order composed rows so every requested dynamic package precedes its consumers.
    """
    rows_by_id = {e["id"]: e for e in entries}
    ordered: List[Dict[str, Any]] = []
    placed: Set[str] = set()
    open_stack: List[str] = []

    def visit(entry: Dict[str, Any]) -> None:
        entry_id = entry["id"]
        if entry_id in placed:
            return
        if entry_id in open_stack:
            cycle_start = open_stack.index(entry_id)
            cycle = open_stack[cycle_start:] + [entry_id]
            raise ValueError(
                f"client-modules: module graph cycle {' -> '.join(cycle)} "
                "— requested package row must precede consumers"
            )
        open_stack.append(entry_id)
        for ext in entry.get("external", []):
            dep_id = ext.split("/")[0] if ext.startswith("@") and "/" in ext else ext
            # Handle scoped packages like @deepseek-ai/dsh-client-ui-theme/client
            if ext.startswith("@"):
                parts = ext.split("/")
                if len(parts) >= 2:
                    dep_id = f"{parts[0]}/{parts[1]}"
            if dep_id in rows_by_id:
                visit(rows_by_id[dep_id])
        open_stack.pop()
        placed.add(entry_id)
        ordered.append(entry)

    for entry in entries:
        visit(entry)

    return ordered


class ClientModuleRegistry:
    """
    Client Module Registry service mounted at `ctx.client_modules` or `ctx.clientModules`.
    """

    def __init__(self, ctx: Any, search_dirs: Optional[List[str]] = None):
        self.ctx = ctx
        self.search_dirs = search_dirs or []
        self._pkg_meta: Dict[str, Dict[str, Any]] = {}
        self._bundle_cache: Dict[str, bytes] = {}
        self._bundle_paths: Dict[str, str] = {}
        self._graph: Optional[Dict[str, Any]] = None
        self._listeners: List[Callable[[], None]] = []

    def add_search_dir(self, directory: str) -> None:
        if os.path.exists(directory) and directory not in self.search_dirs:
            self.search_dirs.append(directory)
            self._graph = None

    def scan_packages(self) -> None:
        """Scan registered search directories for dsh.client packages."""
        self._pkg_meta.clear()
        self._bundle_paths.clear()
        self._bundle_cache.clear()

        for base_dir in self.search_dirs:
            if not os.path.isdir(base_dir):
                continue
            for root, dirs, files in os.walk(base_dir):
                if "package.json" in files:
                    pkg_json_path = os.path.join(root, "package.json")
                    try:
                        with open(pkg_json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        continue

                    pkg_name = data.get("name")
                    dsh_decl = (data.get("dsh") or {}).get("client")
                    if not pkg_name or not dsh_decl:
                        continue

                    if not isinstance(dsh_decl, dict):
                        continue

                    platform = dsh_decl.get("platform", "web")
                    if platform != "web":
                        continue

                    # Look for built client bundle
                    exports = data.get("exports") or {}
                    client_export = None
                    if isinstance(exports, dict):
                        ce = exports.get("./client")
                        if isinstance(ce, str):
                            client_export = ce
                        elif isinstance(ce, dict):
                            client_export = ce.get("default")

                    candidate_paths = []
                    if client_export:
                        candidate_paths.append(os.path.normpath(os.path.join(root, client_export)))
                    candidate_paths.extend([
                        os.path.join(root, "lib", "client.js"),
                        os.path.join(root, "dist", "client.js"),
                        os.path.join(root, "client.js"),
                    ])

                    bundle_path = None
                    for cp in candidate_paths:
                        if os.path.isfile(cp):
                            bundle_path = cp
                            break

                    self._pkg_meta[pkg_name] = {
                        "name": pkg_name,
                        "dir": root,
                        "bundle_path": bundle_path,
                        "inject": dsh_decl.get("inject", []),
                        "immediately": bool(dsh_decl.get("immediately", False)),
                        "external": dsh_decl.get("external", []),
                    }
                    if bundle_path:
                        self._bundle_paths[pkg_name] = bundle_path

        self._compose_graph()

    def _compose_graph(self) -> None:
        raw_entries = []
        for pkg_name, meta in self._pkg_meta.items():
            bundle_path = meta.get("bundle_path")
            rev = "000000000000"
            if bundle_path and os.path.isfile(bundle_path):
                try:
                    with open(bundle_path, "rb") as f:
                        content = f.read()
                    rev = short_hash(content)
                    self._bundle_cache[pkg_name] = content
                except Exception:
                    pass

            entry = {
                "id": pkg_name,
                "url": f"/plugins/{pkg_name}/client.js?rev={rev}",
                "rev": rev,
            }
            if meta.get("inject"):
                entry["inject"] = meta["inject"]
            if meta.get("immediately"):
                entry["immediately"] = True
            if meta.get("external"):
                entry["external"] = meta["external"]
            raw_entries.append(entry)

        try:
            ordered_entries = order_by_module_graph(raw_entries)
        except Exception:
            ordered_entries = raw_entries

        # Graph rev is hash over all entries
        all_revs = "".join(e["rev"] for e in ordered_entries).encode("utf-8")
        graph_rev = short_hash(all_revs) if all_revs else "000000000000"

        self._graph = {
            "rev": graph_rev,
            "entries": ordered_entries,
            "plugins": ordered_entries,
            "modules": ordered_entries,
        }

    def graph(self) -> Dict[str, Any]:
        """Return the current WebBootGraph."""
        if self._graph is None:
            self.scan_packages()
        return self._graph or {"rev": "000000000000", "entries": [], "plugins": [], "modules": []}

    def client_path(self, pkg_id: str) -> Optional[str]:
        """Return the absolute path of a plugin client bundle."""
        if pkg_id not in self._bundle_paths:
            self.scan_packages()
        return self._bundle_paths.get(pkg_id)

    def register_virtual_bundle(self, pkg_id: str, content: bytes, inject: Optional[List[str]] = None, immediately: bool = False) -> None:
        """Register an in-memory virtual bundle."""
        rev = short_hash(content)
        self._bundle_cache[pkg_id] = content
        self._pkg_meta[pkg_id] = {
            "name": pkg_id,
            "bundle_path": f"virtual:{pkg_id}",
            "inject": inject or [],
            "immediately": immediately,
            "external": [],
        }
        self._compose_graph()
        for listener in self._listeners:
            try:
                listener()
            except Exception:
                pass

    def on_graph_changed(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def disposer():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return disposer

    async def handle_plugin_request(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        """Handle GET /plugins/<id>/client.js requests."""
        path = request.get("path", "")
        # Match /plugins/<pkg_id>/client.js or /plugins/<pkg_id>/client.js.map
        # Example: /plugins/@deepseek-ai/dsh-client-ui-layout/client.js
        m = re.match(r"^/plugins/(.+?)/(client\.js(?:\.map)?)$", path)
        if not m:
            response.write_status(404)
            response.write_header("Content-Type", "text/plain; charset=utf-8")
            response.write_body(b"404 Plugin Route Not Found")
            await response.finish()
            return

        raw_pkg_id = unquote(m.group(1))
        file_name = m.group(2)

        if raw_pkg_id in self._bundle_cache:
            data = self._bundle_cache[raw_pkg_id]
            response.write_status(200)
            response.write_header("Content-Type", "application/javascript; charset=utf-8")
            response.write_header("Cache-Control", "no-cache")
            response.write_body(data)
            await response.finish()
            return

        bundle_path = self.client_path(raw_pkg_id)
        if file_name.endswith(".map") and bundle_path:
            map_path = f"{bundle_path}.map"
            if os.path.isfile(map_path):
                try:
                    with open(map_path, "rb") as f:
                        data = f.read()
                    response.write_status(200)
                    response.write_header("Content-Type", "application/json; charset=utf-8")
                    response.write_header("Cache-Control", "no-cache")
                    response.write_body(data)
                    await response.finish()
                    return
                except Exception:
                    pass

        if bundle_path and os.path.isfile(bundle_path):
            try:
                with open(bundle_path, "rb") as f:
                    data = f.read()
                self._bundle_cache[raw_pkg_id] = data
                response.write_status(200)
                response.write_header("Content-Type", "application/javascript; charset=utf-8")
                response.write_header("Cache-Control", "no-cache")
                response.write_body(data)
                await response.finish()
                return
            except Exception as e:
                response.write_status(500)
                response.write_header("Content-Type", "text/plain; charset=utf-8")
                response.write_body(f"500 Error reading bundle: {e}".encode("utf-8"))
                await response.finish()
                return

        response.write_status(404)
        response.write_header("Content-Type", "text/plain; charset=utf-8")
        response.write_body(f"404 Client bundle not found for {raw_pkg_id}".encode("utf-8"))
        await response.finish()

    def tap_index(self, html: str) -> str:
        """Inject window.__DSH_BOOT__ manifest into HTML index response."""
        g = self.graph()
        boot_json = json.dumps(g, ensure_ascii=False)
        # Escape '<' to prevent breaking out of script tag
        safe_boot_json = boot_json.replace("<", "\\u003c")
        manifest_script = (
            f'<script>\n'
            f'window.__DSH_BOOT__ = {safe_boot_json};\n'
            f'window.__ModuleLoader__ = window.__ModuleLoader__ || {{\n'
            f'  mode: "queue",\n'
            f'  pendingQueue: [],\n'
            f'  load: function(r) {{ (this.pendingQueue = this.pendingQueue || []).push(r); }}\n'
            f'}};\n'
            f'</script>'
        )

        if "<head>" in html:
            return html.replace("<head>", f"<head>\n  {manifest_script}", 1)
        elif "<title>" in html:
            return html.replace("<title>", f"{manifest_script}\n  <title>", 1)
        else:
            return f"{manifest_script}\n{html}"


class ClientModulesPlugin(Plugin):
    """
    Plugin `@deepseek-ai/dsh-client-modules`: Serves client bundle endpoints & injects boot manifest.
    """

    id = "client-modules"
    name = "@deepseek-ai/dsh-client-modules"
    inject = ["web_server"]

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.search_dirs = (config or {}).get("search_dirs", [])
        self.registry: Optional[ClientModuleRegistry] = None

    def apply(self, ctx: Any) -> None:
        web_server: WebServerService = ctx.get("web_server") or ctx.get("webServer")
        if not web_server:
            return

        # Default package search directories
        default_dirs = [
            os.path.join(os.getcwd(), "reference", "deepseek-harness", "packages", "client"),
            os.path.join(os.getcwd(), "packages", "client"),
            os.path.join(os.getcwd(), "dsh", "client"),
            os.path.join(os.getcwd(), "apps", "web"),
        ]
        all_dirs = list(self.search_dirs) + default_dirs

        self.registry = ClientModuleRegistry(ctx, search_dirs=all_dirs)
        ctx.set_service("client_modules", self.registry)
        ctx.set_service("clientModules", self.registry)

        # Register /plugins route
        disposer_route = web_server.register("prefix", "/plugins", self.registry.handle_plugin_request)
        # Register index tap
        disposer_tap = web_server.tap_index(self.registry.tap_index)

        if hasattr(ctx, "effect"):
            ctx.effect(disposer_route)
            ctx.effect(disposer_tap)
