"""
Client Module Registry (`@deepseek-ai/dsh-client-modules`) for Windows 7 Python 3.8 backend.
Scans package.json declarations for dsh.client packages, computes bundle revisions,
orders topological module graphs, serves /plugins/<id>/client.js, and injects window.__DSH_BOOT__.
Aligned 1:1 with official DeepSeek Harness Cordis in Browser architecture.
"""

import hashlib
import json
import os
import re
from urllib.parse import unquote
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dsh.cordis.plugin import Plugin
from dsh.host.webserver.webserver import HttpResponseWriter, WebServerService

# Bootstrap package whose ordinary client bundle supplies the module-system
# implementation (upstream `CLIENT_MODULES_ID`), and the one parser-preload id
# ahead of the shell (upstream `PARSER_PRELOAD_IDS`).
CLIENT_MODULES_ID = "@deepseek-ai/dsh-client-modules"
PARSER_PRELOAD_IDS: Tuple[str, ...] = (CLIENT_MODULES_ID,)

# Official Web roster from packages/bundle/web-app/cordis.patch.yml
OFFICIAL_WEB_ROSTER: Set[str] = {
    "@deepseek-ai/dsh-client-modules",
    "@deepseek-ai/dsh-client-connection",
    "@deepseek-ai/dsh-client-hmr",
    "@deepseek-ai/dsh-api-remotes",
    "@deepseek-ai/dsh-api-gateway",
    "@deepseek-ai/dsh-api-session-controller",
    "@deepseek-ai/dsh-api-workspace-controller",
    "@deepseek-ai/dsh-typert-registry",
    "@deepseek-ai/dsh-cordis-client-runner",
    "@deepseek-ai/dsh-client-ui-theme",
    "@deepseek-ai/dsh-client-locale",
    "@deepseek-ai/dsh-client-ui-layout",
    "@deepseek-ai/dsh-client-ui-renderer",
    "@deepseek-ai/dsh-client-ui-session",
    "@deepseek-ai/dsh-client-ui-sidebar",
    "@deepseek-ai/dsh-client-ui-settings",
    "@deepseek-ai/dsh-client-ui-settings-general",
    "@deepseek-ai/dsh-client-ui-settings-models",
    "@deepseek-ai/dsh-client-ui-settings-plugin-inventory",
    "@deepseek-ai/dsh-client-ui-conversation",
    "@deepseek-ai/dsh-client-ui-approval",
    "@deepseek-ai/dsh-client-ui-chat",
    "@deepseek-ai/dsh-client-ui-brand-official",
    "@deepseek-ai/dsh-client-ui-attachment",
    "@deepseek-ai/dsh-client-ui-tool",
    "@deepseek-ai/dsh-client-ui-cordis",
    "@deepseek-ai/dsh-client-ui-workflow-run",
    "@deepseek-ai/dsh-client-ui-deliverables",
    "@deepseek-ai/dsh-client-ui-workspace",
    "@deepseek-ai/dsh-client-ui-input-trigger",
    "@deepseek-ai/dsh-client-ui-commands",
    "@deepseek-ai/dsh-client-ui-skill",
    "@deepseek-ai/dsh-client-ui-subagent",
    "@deepseek-ai/dsh-client-ui-reference",
    "@deepseek-ai/dsh-client-ui-jobs",
    "@deepseek-ai/dsh-client-ui-goal",
    "@deepseek-ai/dsh-client-ui-message-feedback",
    "@deepseek-ai/dsh-client-ui-model-selection",
    "@deepseek-ai/dsh-client-ui-permission-presets",
    "@deepseek-ai/dsh-client-ui-agent-preset",
    "@deepseek-ai/dsh-client-ui-settings-plugins",
    "@deepseek-ai/dsh-client-ui-plan",
    "@deepseek-ai/dsh-client-ui-user-questions",
    "@deepseek-ai/dsh-client-ui-trajectory",
    "@deepseek-ai/dsh-session-log-export",
}


def short_hash(data: bytes) -> str:
    """Compute 12-char SHA-1 hash for bundle or graph consistency anchor."""
    return hashlib.sha1(data).hexdigest()[:12]


# Recovery instruction shared by grouped startup and steady-state bundle diagnostics.
CLIENT_BUNDLE_BUILD_INSTRUCTION = "run `pnpm run build` before launch"


class MissingClientBundleError(Exception):
    """Missing built client export, retained for activation-error grouping."""

    def __init__(self, package_name: str, client_path: str, cause: Optional[BaseException] = None):
        super().__init__(
            "client-modules: client bundle not found; %s:\n  package: %s\n  path: %s"
            % (CLIENT_BUNDLE_BUILD_INSTRUCTION, package_name, client_path)
        )
        self.package_name = package_name
        self.client_path = client_path
        self.cause = cause


class ClientPackageCompositionError(Exception):
    """Activation failures grouped by actionable package-build errors and unrelated failures."""

    def __init__(self, failures: List[BaseException]):
        self.failures = list(failures)
        missing = [f for f in self.failures if isinstance(f, MissingClientBundleError)]
        other = [f for f in self.failures if not isinstance(f, MissingClientBundleError)]
        noun = "package" if len(self.failures) == 1 else "packages"
        lines = ["client-modules: %d client %s failed to compose:" % (len(self.failures), noun)]
        if missing:
            lines.append("  client bundles not found; %s:" % CLIENT_BUNDLE_BUILD_INSTRUCTION)
            for error in missing:
                lines.append("    - package: %s" % error.package_name)
                lines.append("      path: %s" % error.client_path)
        if other:
            lines.append("  other failures:")
            for error in other:
                lines.append("    - %s" % error)
        super().__init__("\n".join(lines))


def optional_string_array(subject: str, field: str, value: Any) -> Optional[List[str]]:
    """
    Validate an optional string-array field read from a `dsh.client`
    declaration. Absent fields return None; a present non-array (or an array
    holding a non-string) throws, because a malformed declaration must fail the
    load loudly rather than silently dropping graph edges.
    """
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"client-modules: {subject} {field} must be a string array")
    return list(value)


def parse_dsh_client(pkg_name: str, value: Any) -> Optional[Dict[str, Any]]:
    """Narrow the parsed JSON value to the `dsh.client` declaration, throwing on malformed fields."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"client-modules: {pkg_name} has a non-object dsh.client declaration")
    if not isinstance(value.get("platform"), str):
        raise ValueError(f"client-modules: {pkg_name} dsh.client.platform must be a string")
    inject = optional_string_array(pkg_name, "dsh.client.inject", value.get("inject"))
    external = optional_string_array(pkg_name, "dsh.client.external", value.get("external"))
    immediately = value.get("immediately")
    if immediately is not None and not isinstance(immediately, bool):
        raise ValueError(f"client-modules: {pkg_name} dsh.client.immediately must be a boolean")
    return {
        "platform": value.get("platform"),
        "inject": inject,
        "external": external,
        "immediately": immediately,
    }


def client_export_of(pkg_name: str, exports_field: Any) -> Optional[str]:
    """Resolve `exports["./client"]` to a relative path, accepting the string and one-level conditional forms."""
    if not isinstance(exports_field, dict):
        return None
    if "./client" not in exports_field:
        return None
    client = exports_field.get("./client")
    if isinstance(client, str):
        return client
    if isinstance(client, dict) and isinstance(client.get("default"), str):
        return client["default"]
    raise ValueError(
        f'client-modules: {pkg_name} exports["./client"] must be a string or an object with a string default'
    )


def strip_client_suffix(spec: str) -> str:
    """
    Normalize a module specifier onto the graph row that owns it: a plugin
    bundle IS its package's client half, so `<id>/client` and the bare package
    name resolve to the same exports.
    """
    return spec[:-len("/client")] if spec.endswith("/client") else spec


def order_by_module_graph(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Order composed rows so every requested dynamic package precedes its
    consumers. An `external` specifier is either the package row it names
    (`<pkg>/client` aliases the bare package) or a static-table name that adds
    no graph edge. `inject` is a Cordis service edge, never a module-graph one.
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
        for name in entry.get("external") or []:
            if not isinstance(name, str):
                continue
            dependency = rows_by_id.get(name) or rows_by_id.get(strip_client_suffix(name))
            if dependency is entry:
                raise ValueError(
                    f'client-modules: "{entry_id}" requests module "{name}" that it answers itself '
                    "\u2014 a row must not declare its own package in dsh.client.external"
                )
            if dependency is not None:
                visit(dependency)
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

    def __init__(self, ctx: Any, search_dirs: Optional[List[str]] = None, roster: Optional[Set[str]] = None):
        self.ctx = ctx
        self.search_dirs = search_dirs or []
        self._pkg_meta: Dict[str, Dict[str, Any]] = {}
        self._bundle_cache: Dict[str, bytes] = {}
        self._bundle_paths: Dict[str, str] = {}
        self._graph: Optional[Dict[str, Any]] = None
        self._listeners: List[Callable[[], None]] = []
        self._roster: Set[str] = set(roster) if roster is not None else set(OFFICIAL_WEB_ROSTER)
        self._dynamic_surfaces: Set[str] = set()

    def add_search_dir(self, directory: str) -> None:
        if os.path.exists(directory) and directory not in self.search_dirs:
            self.search_dirs.append(directory)
            self._graph = None

    def register_dynamic_surface(self, package_name: str) -> None:
        """Register a dynamic capability seam surface (e.g. from DirectoryPickerAutoPlugin)."""
        self._dynamic_surfaces.add(package_name)
        self._graph = None

    def include_package(self, package_name: str) -> None:
        """Alias for register_dynamic_surface."""
        self.register_dynamic_surface(package_name)

    def scan_packages(self) -> None:
        """Scan registered search directories for dsh.client packages."""
        self._pkg_meta.clear()
        self._bundle_paths.clear()
        self._bundle_cache.clear()

        for base_dir in self.search_dirs:
            if not os.path.isdir(base_dir):
                continue
            for root, dirs, files in os.walk(base_dir):
                dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", ".venv")]
                if "package.json" in files:
                    pkg_json_path = os.path.join(root, "package.json")
                    try:
                        with open(pkg_json_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                    except Exception:
                        continue

                    pkg_name = data.get("name")
                    dsh_decl = (data.get("dsh") or {}).get("client")
                    if not pkg_name or dsh_decl is None:
                        continue

                    # Only mounted client rows are composed: the Web roster and
                    # the active dynamic capability seams. Everything else in
                    # the tree is not a client row at all.
                    if self._roster and pkg_name not in (self._roster | self._dynamic_surfaces):
                        continue

                    decl = parse_dsh_client(pkg_name, dsh_decl)
                    if decl is None or decl.get("platform") != "web":
                        continue

                    client_rel = client_export_of(pkg_name, data.get("exports"))
                    if client_rel is None:
                        raise ValueError(
                            f'client-modules: {pkg_name} declares dsh.client but exports no "./client" bundle'
                        )

                    client_path = os.path.normpath(os.path.join(root, client_rel))
                    self._pkg_meta[pkg_name] = {
                        "name": pkg_name,
                        "dir": root,
                        "client_path": client_path,
                        # A directory in the bundle's place exists but cannot be
                        # read: it is an "other" composition failure, not a
                        # missing build (upstream readFile's EISDIR arm).
                        "bundle_path": client_path if os.path.exists(client_path) else None,
                        "inject": decl.get("inject") or [],
                        "immediately": decl.get("immediately") is True,
                        "external": decl.get("external") or [],
                    }
                    self._bundle_paths[pkg_name] = client_path

        self._compose_graph()

    def _compose_graph(self) -> None:
        raw_entries = []
        allowed_packages = self._roster | self._dynamic_surfaces
        missing: List[MissingClientBundleError] = []
        other_failures: List[BaseException] = []

        for pkg_name, meta in self._pkg_meta.items():
            # In official Cordis, only packages part of the Web App roster or active dynamic capability seams are composed
            if self._roster and pkg_name not in allowed_packages:
                continue

            bundle_path = meta.get("bundle_path")
            client_path = meta.get("client_path") or bundle_path
            if meta.get("virtual"):
                # An in-memory bundle registered by a dynamic capability seam.
                rev = short_hash(self._bundle_cache.get(pkg_name) or b"")
                entry = {"id": pkg_name, "url": f"/plugins/{pkg_name}/client.js?rev={rev}", "rev": rev}
                if meta.get("inject"):
                    entry["inject"] = meta["inject"]
                if meta.get("immediately"):
                    entry["immediately"] = True
                if meta.get("external"):
                    entry["external"] = meta["external"]
                raw_entries.append(entry)
                continue
            if not bundle_path:
                missing.append(MissingClientBundleError(pkg_name, client_path))
                continue
            try:
                if os.path.isdir(bundle_path):
                    raise IsADirectoryError(21, "EISDIR: illegal operation on a directory", bundle_path)
                with open(bundle_path, "rb") as f:
                    content = f.read()
            except OSError as error:
                # A bundle that exists but cannot be read is not a missing
                # build: it is reported under the composition's other failures.
                other_failures.append(error)
                continue
            rev = short_hash(content)
            self._bundle_cache[pkg_name] = content

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

        if missing or other_failures:
            raise ClientPackageCompositionError(list(missing) + list(other_failures))

        ordered_entries = order_by_module_graph(raw_entries)

        graph_json = json.dumps(ordered_entries, sort_keys=True).encode("utf-8")
        graph_rev = short_hash(graph_json)

        self._graph = {
            "rev": graph_rev,
            "entries": ordered_entries,
            "plugins": ordered_entries,
        }

    def graph(self) -> Dict[str, Any]:
        """Return the current composed WebBootGraph (window.__DSH_BOOT__)."""
        if self._graph is None:
            self.scan_packages()
        return self._graph or {"rev": "empty", "entries": [], "plugins": []}

    def client_path(self, pkg_id: str) -> Optional[str]:
        """Return the absolute path of a package's client bundle."""
        if not self._pkg_meta:
            self.scan_packages()
        return self._bundle_paths.get(pkg_id)

    def register_virtual_bundle(self, pkg_id: str, bundle_content: bytes, inject: Optional[List[str]] = None, immediately: bool = False) -> None:
        """Register an in-memory client bundle."""
        rev = short_hash(bundle_content)
        self._bundle_cache[pkg_id] = bundle_content
        self._roster.add(pkg_id)
        self._pkg_meta[pkg_id] = {
            "name": pkg_id,
            "dir": "",
            "bundle_path": "",
            "client_path": "",
            "virtual": True,
            "inject": inject or [],
            "immediately": immediately,
            "external": [],
        }
        self._compose_graph()

    async def handle_plugin_request(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        """
        Handle `GET /plugins/<id>/client.js` and `GET /plugins/<id>/client.js.map`.
        """
        method = request.get("method", "GET")
        if method not in ("GET", "HEAD"):
            response.write_status(405)
            response.write_header("Content-Type", "text/plain; charset=utf-8")
            response.write_body(b"405 Method Not Allowed")
            await response.finish()
            return

        path: str = request.get("path", "")
        m = re.match(r"^/plugins/((?:@[^/]+/)?[^/]+)/client\.js(\.map)?$", path)
        if not m:
            response.write_status(404)
            response.write_header("Content-Type", "text/plain; charset=utf-8")
            response.write_body(b"404 Plugin Route Not Found")
            await response.finish()
            return

        raw_pkg_id = unquote(m.group(1))
        is_map = bool(m.group(2))

        if not is_map and raw_pkg_id in self._bundle_cache:
            data = self._bundle_cache[raw_pkg_id]
            response.write_status(200)
            response.write_header("Content-Type", "application/javascript; charset=utf-8")
            response.write_header("Cache-Control", "no-cache")
            response.write_body(data)
            await response.finish()
            return

        bundle_path = self.client_path(raw_pkg_id)
        if is_map and bundle_path:
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
        """
        Render the boot protocol rows into a served seed document.

        The head rows, in execution order: the inline registration queue facade,
        the parser-preload scripts, and the `window.__DSH_BOOT__` graph global.
        These are the head rows upstream `bootInjections` contributes ahead of
        the built `apps/web/dist` document, whose client entry reads
        `window.__ModuleLoader__` and `window.__DSH_BOOT__` and refuses to boot
        without them. The boot-readiness tail that follows the same rows is
        rendered by the webserver injection table.
        """
        g = self.graph()
        boot_json = json.dumps(g, ensure_ascii=False).replace("<", "\\u003c")
        
        # The parser-preload tier: the module-system bundle registers itself
        # through the queue facade, so its script is parser-blocking and
        # precedes every application row (upstream `PARSER_PRELOAD_IDS`).
        preload_scripts = []
        for pid in PARSER_PRELOAD_IDS:
            for entry in g.get("entries", []):
                if entry.get("id") == pid:
                    url = entry.get("url")
                    preload_scripts.append(f'<script src="{url}"></script>')
                    break
        preload_html = "".join(preload_scripts)

        bootstrap_script = (
            f'<script>(()=>{{'
            f'const pendingQueue=[];'
            f'window.__ModuleLoader__={{'
            f'  mode:"queue",'
            f'  pendingQueue,'
            f'  load(registration){{pendingQueue.push(registration)}},'
            f'  create(options){{'
            f'    if(this.mode!=="queue")throw new Error("client-modules: window.__ModuleLoader__.create called after module-system boot");'
            f'    const index=pendingQueue.findIndex(r=>r.id==="@deepseek-ai/dsh-client-modules");'
            f'    const registration=pendingQueue[index];'
            f'    if(registration===undefined)throw new Error("client-modules: HTML did not preload @deepseek-ai/dsh-client-modules/client.js");'
            f'    pendingQueue.splice(index,1);'
            f'    const exports=registration.factory(specifier=>{{'
            f'      throw new Error("client-modules: @deepseek-ai/dsh-client-modules/client.js requested external \\""+specifier+"\\" before the module system existed");'
            f'    }});'
            f'    if(typeof exports!=="object"||exports===null||typeof exports.createClientModuleSystem!=="function"||typeof exports.apply!=="function"){{'
            f'      throw new Error("client-modules: @deepseek-ai/dsh-client-modules/client.js did not export the bootstrap module face");'
            f'    }}'
            f'    return exports.createClientModuleSystem(this,{{id:registration.id,exports}},options);'
            f'  }}'
            f'}};'
            f'}})()</script>'
            f'{preload_html}'
            f'<script>window.__DSH_BOOT__ = {boot_json};</script>'
        )

        if "<head>" in html:
            out = html.replace("<head>", f"<head>\n  {bootstrap_script}", 1)
        elif "<title>" in html:
            out = html.replace("<title>", f"{bootstrap_script}\n  <title>", 1)
        else:
            out = f"{bootstrap_script}\n{html}"

        return out


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

        # Default package search directories. The package tree lives beside the
        # framework package, not beside whatever directory the process was
        # launched from: the portable launcher starts `python <app>/dsh.py`
        # without changing directory, and the served boot graph must not depend
        # on the caller cwd (an unresolved graph injects no preload and the shell
        # cannot boot).
        app_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        default_dirs: List[str] = []
        for root in (os.getcwd(), app_root):
            for rel in (("packages",), ("reference", "deepseek-harness", "packages"),
                        ("dsh", "client"), ("apps", "web")):
                candidate = os.path.join(root, *rel)
                if candidate not in default_dirs:
                    default_dirs.append(candidate)
        all_dirs = list(self.search_dirs) + default_dirs

        self.registry = ClientModuleRegistry(ctx, search_dirs=all_dirs)
        ctx.set_service("client_modules", self.registry)
        ctx.set_service("clientModules", self.registry)

        # Register /plugins route
        disposer_route = web_server.register("prefix", "/plugins", self.registry.handle_plugin_request)
        # Register index tap
        disposer_tap = web_server.tap_index(self.registry.tap_index)

        if hasattr(ctx, "effect"):
            ctx.effect(lambda: disposer_route)
            ctx.effect(lambda: disposer_tap)
