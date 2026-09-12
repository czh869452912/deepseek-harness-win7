"""
Client Module Registry (`@deepseek-ai/dsh-client-modules`) for Windows 7 Python 3.8 backend.
Scans package.json declarations for dsh.client packages, composes the served boot
graph ({rev, entries, batches}) with generated combo URLs, serves the combo and
combo-source-map responses with immutable caching, and contributes the boot rows
(registration queue, application preloads, blocking bootstrap batch, graph
global) to the webserver injection table.
Aligned 1:1 with official DeepSeek Harness Cordis in Browser architecture.
"""

import errno
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

# Versioned code is immutable; mismatched revisions are rejected instead of
# serving newer bytes (upstream `IMMUTABLE_CACHE`).
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"

# Generated request URLs stay below conservative browser and intermediary
# request-target limits (upstream `MAX_COMBO_URL_BYTES`).
MAX_COMBO_URL_BYTES = 3 * 1024
HASH_REVISION_LENGTH = 12
COMBO_REVISION_PLACEHOLDER = "0" * HASH_REVISION_LENGTH
JAVASCRIPT_CONTENT_TYPE = "text/javascript; charset=utf-8"
JSON_CONTENT_TYPE = "application/json; charset=utf-8"

# Source-map trailer emitted by the bundler at the end of every client
# bundle, and the debugger source name appended to page bundles.
SOURCE_MAP_TRAILER = re.compile(r"(?:\r?\n)?//# sourceMappingURL=[^\r\n]*(?:\r?\n)?$")
SOURCE_URL_TRAILER = re.compile(r"(?:\r?\n)?//# sourceURL=([^\r\n]+)(?:\r?\n)?$")

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


def framed_hash(domain: str, parts: List[bytes]) -> str:
    """Hash several response fields without allowing bytes across boundaries."""
    digest = hashlib.sha1()
    digest.update(domain.encode("utf-8"))
    digest.update(b"\0")
    for part in parts:
        digest.update(("%d:" % len(part)).encode("utf-8"))
        digest.update(part)
    return digest.hexdigest()[:HASH_REVISION_LENGTH]


def artifact_revision(bundle: bytes, source_map: Optional[Dict[str, Any]]) -> str:
    """Hash every artifact input served after one plugin change was observed."""
    parts = [bundle] if source_map is None else [bundle, source_map["body"]]
    return framed_hash("plugin-artifact", parts)


def combo_url(ids: List[str], rev: str, source_map: bool = False) -> str:
    """Address one ordered plugin-file list through the shared combo route."""
    suffix = ".map" if source_map else ""
    resources = ",".join("%s/client.js%s" % (plugin_id, suffix) for plugin_id in ids)
    return "/plugins/??%s&rev=%s" % (resources, rev)


def projected_combo_url_bytes(records: List[Dict[str, Any]]) -> int:
    """Measure the longer map-form URL used to partition a startup list."""
    return len(
        combo_url([record["id"] for record in records], COMBO_REVISION_PLACEHOLDER, True).encode("utf-8")
    )


def partition_combo_records(records: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Partition one phase in graph order without exceeding the URL limit."""
    chunks: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for record in records:
        candidate = current + [record]
        if projected_combo_url_bytes(candidate) <= MAX_COMBO_URL_BYTES:
            current = candidate
            continue
        if not current:
            raise ValueError(
                "client-modules: %s exceeds the %d-byte combo URL limit"
                % (record["id"], MAX_COMBO_URL_BYTES)
            )
        chunks.append(current)
        current = [record]
        if projected_combo_url_bytes(current) > MAX_COMBO_URL_BYTES:
            raise ValueError(
                "client-modules: %s exceeds the %d-byte combo URL limit"
                % (record["id"], MAX_COMBO_URL_BYTES)
            )
    if current:
        chunks.append(current)
    return chunks


def combo_source(record: Dict[str, Any]) -> Tuple[str, str]:
    """
    Strip bundle-local debug directives and retain the stable generated name.

    Returns `(source, fallbackSource)`; the fallback name is the map's source
    when the bundle declares an absolute-looking `//# sourceURL`, else the
    plugin's own `/plugins/<id>/client.js`.
    """
    source = record["bundle"].decode("utf-8", errors="replace")
    match = SOURCE_URL_TRAILER.search(source)
    source_url = match.group(1) if match else None
    source = SOURCE_URL_TRAILER.sub("", source)
    source = SOURCE_MAP_TRAILER.sub("", source)
    if not source.endswith("\n"):
        source += "\n"
    if source_url is None:
        fallback = "/plugins/%s/client.js" % record["id"]
    elif re.match(r"^(?:[A-Za-z][A-Za-z\d+.-]*:|/)", source_url):
        fallback = source_url
    else:
        fallback = "/" + source_url
    return source, fallback


def combo_script(source: str, source_map_url: Optional[str] = None) -> bytes:
    """Stamp a combo script's absolute indexed-map URL onto its bytes."""
    if source_map_url is None:
        return source.encode("utf-8")
    return ("%s//# sourceMappingURL=%s\n" % (source, source_map_url)).encode("utf-8")


def validate_source_map(client_path: str, body: bytes) -> Dict[str, Any]:
    """Parse one authored Source Map v3 artifact, or raise `ValueError`."""
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        parsed = None
    if (
        not isinstance(parsed, dict)
        or parsed.get("version") != 3
        or not isinstance(parsed.get("sources"), list)
        or any(not isinstance(source, str) for source in parsed["sources"])
        or not isinstance(parsed.get("names"), list)
        or any(not isinstance(name, str) for name in parsed["names"])
        or not isinstance(parsed.get("mappings"), str)
    ):
        raise ValueError("client-modules: %s.map is not a regular Source Map v3 object" % client_path)
    return parsed


def newline_count(value: str) -> int:
    """Count generated lines while assembling indexed-map section offsets."""
    return value.count("\n")


def relocate_source(source_root: str, source: str, base_path: str) -> str:
    """
    Resolve one section source against its original per-plugin map URL.

    The base is the plugin's own `/plugins/<id>/client.js.map`; a source that
    resolves inside that same origin is reduced to path/search/hash, and
    anything else keeps its absolute form.
    """
    separator = "/" if source_root != "" and not source_root.endswith("/") and not source.startswith("/") else ""
    base_dir = base_path.rsplit("/", 1)[0]
    joined = source_root + separator + source
    if re.match(r"^[A-Za-z][A-Za-z\d+.-]*:", joined):
        return joined
    if joined.startswith("/"):
        resolved = joined
    else:
        resolved = base_dir + "/" + joined
    parts = resolved.split("?")
    path_only = parts[0]
    query = "?" + parts[1] if len(parts) > 1 else ""
    normalized: List[str] = []
    for segment in path_only.split("/"):
        if segment == "." or segment == "":
            continue
        if segment == "..":
            if normalized:
                normalized.pop()
            continue
        normalized.append(segment)
    return "/" + "/".join(normalized) + query


def combo_section_map(record: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve section sources against the original per-plugin map URL."""
    original = dict(record["source_map"]["parsed"])
    source_root = original.get("sourceRoot") if isinstance(original.get("sourceRoot"), str) else ""
    base_path = "/plugins/%s/client.js.map" % record["id"]
    original["sources"] = [
        relocate_source(source_root, source, base_path) for source in original["sources"]
    ]
    original.pop("sourceRoot", None)
    return original


def identity_section_map(source: str, source_url: str) -> Dict[str, Any]:
    """Map each generated line to the same line in a bundled JavaScript source."""
    mappings = ";".join("AAAA" if index == 0 else "AACA" for index in range(newline_count(source)))
    return {
        "version": 3,
        "names": [],
        "sources": [source_url],
        "sourcesContent": [source],
        "mappings": mappings,
    }


def build_combo(records: List[Dict[str, Any]], revision: Optional[str] = None) -> Dict[str, Any]:
    """Concatenate factory registrations and compose their maps as sections."""
    source = ""
    sections: List[Dict[str, Any]] = []
    line = 0
    for record in records:
        prepared_source, fallback_source = combo_source(record)
        if record["source_map"] is None:
            section = identity_section_map(prepared_source, fallback_source)
        else:
            section = combo_section_map(record)
        sections.append({"offset": {"line": line, "column": 0}, "map": section})
        bundle = "%s;\n" % prepared_source
        source += bundle
        line += newline_count(bundle)
    source_map = (json.dumps({"version": 3, "file": "client.js", "sections": sections}) + "\n").encode("utf-8")
    source_bytes = source.encode("utf-8")
    rev = revision if revision is not None else framed_hash("combo", [source_bytes, source_map])
    entries = [record["id"] for record in records]
    url = combo_url(entries, rev)
    source_map_url = combo_url(entries, rev, True)
    return {
        "url": url,
        "rev": rev,
        "entries": entries,
        "script": combo_script(source, source_map_url),
        "sourceMap": source_map,
        "sourceMapUrl": source_map_url,
    }


def build_batch(phase: str, records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Add initial-load scheduling metadata to a combo artifact."""
    artifact = build_combo(records)
    descriptor = {
        "phase": phase,
        "url": artifact["url"],
        "rev": artifact["rev"],
        "entries": artifact["entries"],
    }
    return {
        "phase": phase,
        "url": artifact["url"],
        "rev": artifact["rev"],
        "entries": artifact["entries"],
        "script": artifact["script"],
        "sourceMap": artifact["sourceMap"],
        "sourceMapUrl": artifact["sourceMapUrl"],
        "descriptor": descriptor,
    }


def graph_row(package_id: str, rev: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Graph row for one bundle rev (the url carries the rev as its query)."""
    row: Dict[str, Any] = {"id": package_id, "url": combo_url([package_id], rev), "rev": rev}
    if fields.get("inject") is not None:
        row["inject"] = fields["inject"]
    if fields.get("immediately"):
        row["immediately"] = True
    if fields.get("external"):
        row["external"] = fields["external"]
    return row




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


class _Absent:
    """
    Stand-in for JavaScript's `undefined` at the JSON boundary.

    Python collapses a missing key and an explicit JSON `null` into `None`, but
    the reference parser distinguishes them: `undefined` means "no declaration"
    while `null` is a malformed declaration that must fail the load loudly
    (upstream `parseDshClient` / `optionalStringArray`).
    """

    _instance: Optional["_Absent"] = None

    def __new__(cls) -> "_Absent":
        if cls._instance is None:
            cls._instance = super(_Absent, cls).__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ABSENT"


#: The JavaScript `undefined` analogue: a key that is not present at all.
ABSENT = _Absent()


def optional_string_array(subject: str, field: str, value: Any) -> Optional[List[str]]:
    """
    Validate an optional string-array field read from a `dsh.client`
    declaration. Absent fields (upstream `undefined`) return None; a present
    non-array (including an explicit JSON `null`) or an array holding a
    non-string throws, because a malformed declaration must fail the load
    loudly rather than silently dropping graph edges.
    """
    if value is ABSENT:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"client-modules: {subject} {field} must be a string array")
    return list(value)


def parse_dsh_client(pkg_name: str, value: Any) -> Optional[Dict[str, Any]]:
    """
    Narrow the parsed JSON value to the `dsh.client` declaration, throwing on
    malformed fields. `ABSENT` (upstream `undefined`) means the package
    declares nothing; a JSON `null` is a present, malformed declaration.
    """
    if value is ABSENT:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"client-modules: {pkg_name} has a non-object dsh.client declaration")
    platform = value.get("platform", ABSENT)
    if not isinstance(platform, str):
        raise ValueError(f"client-modules: {pkg_name} dsh.client.platform must be a string")
    inject = optional_string_array(pkg_name, "dsh.client.inject", value.get("inject", ABSENT))
    external = optional_string_array(pkg_name, "dsh.client.external", value.get("external", ABSENT))
    immediately = value.get("immediately", ABSENT)
    if immediately is not ABSENT and not isinstance(immediately, bool):
        raise ValueError(f"client-modules: {pkg_name} dsh.client.immediately must be a boolean")
    decl: Dict[str, Any] = {"platform": platform}
    if inject is not None:
        decl["inject"] = inject
    if external is not None:
        decl["external"] = external
    if immediately is not ABSENT:
        decl["immediately"] = immediately
    return decl


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
        self._table: Dict[str, Dict[str, Any]] = {}
        self._graph: Optional[Dict[str, Any]] = None
        self._composed: Optional[Dict[str, Any]] = None
        self._responses: Dict[str, Dict[str, Any]] = {}
        self._batch_responses: Dict[str, Dict[str, Any]] = {}
        self._previous_batch_responses: Dict[str, Dict[str, Any]] = {}
        self._listeners: List[Callable[[], None]] = []
        self.rebuild_listeners: List[Callable[[str, str], None]] = []
        self._roster: Set[str] = set(roster) if roster is not None else set(OFFICIAL_WEB_ROSTER)
        self._dynamic_surfaces: Set[str] = set()
        # Opaque startup revisions: an initial row revision is allocated without
        # inspecting artifact bytes (upstream `allocateInitialRevision`).
        self._initial_revision_nonce = os.urandom(8).hex()
        self._next_initial_revision = 0

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

    def allocate_initial_revision(self) -> str:
        """Allocate an opaque initial row revision without reading artifact bytes."""
        rev = "%s-%d" % (self._initial_revision_nonce, self._next_initial_revision)
        self._next_initial_revision += 1
        return rev

    def capture_artifact_baseline(self, client_path: str) -> Dict[str, Any]:
        """Capture the bundle stats before reading its bytes."""
        info = os.stat(client_path)
        return {"path": client_path, "mtimeMs": info.st_mtime * 1000.0, "size": info.st_size}

    def initial_bundle_snapshot(self, pkg_name: str, client_path: str) -> Tuple[Dict[str, Any], bytes, Optional[Dict[str, Any]]]:
        """
        Read the activation-time bundle and optional source-map snapshot.

        A missing bundle is a missing build; every other filesystem failure
        propagates unchanged (the composition's "other failures" arm).
        """
        try:
            if os.path.isdir(client_path):
                # A directory in the bundle's place: Windows reports opening it
                # as a permission failure, while the reference read reports
                # EISDIR. Keep that classification, because the composition
                # groups failures by it (a directory is not a missing build).
                raise IsADirectoryError(errno.EISDIR, "EISDIR: illegal operation on a directory", client_path)
            baseline = self.capture_artifact_baseline(client_path)
            with open(client_path, "rb") as handle:
                bundle = handle.read()
            source_map = self.read_source_map_snapshot(client_path)
        except OSError as error:
            if getattr(error, "errno", None) != errno.ENOENT:
                raise
            raise MissingClientBundleError(pkg_name, client_path, error)
        return baseline, bundle, source_map

    def read_source_map_snapshot(self, client_path: str) -> Optional[Dict[str, Any]]:
        """Treat a missing, torn or malformed development map as no map at all."""
        try:
            with open("%s.map" % client_path, "rb") as handle:
                body = handle.read()
            return {"body": body, "parsed": validate_source_map(client_path, body)}
        except Exception as error:
            self._log_warn(error)
            return None

    def _log_warn(self, error: Any) -> None:
        try:
            if self.ctx is not None and hasattr(self.ctx, "logger"):
                self.ctx.logger("client-modules").warn(error)
        except Exception:
            pass

    def scan_packages(self) -> None:
        """Scan registered search directories for dsh.client packages."""
        self._pkg_meta.clear()
        self._bundle_paths.clear()
        self._bundle_cache.clear()
        # A fresh scan is a fresh startup composition: every row allocates a new
        # opaque revision, exactly like the reference activation flush.
        self._table.clear()

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
                    # A `dsh` value that is absent, null, or not an object
                    # carries no declaration at all (upstream's
                    # `dsh !== null && typeof dsh === 'object' ? dsh.client : undefined`);
                    # an explicit `"client": null` inside an object is present
                    # and therefore malformed.
                    dsh_field = data.get("dsh", ABSENT)
                    if isinstance(dsh_field, dict):
                        dsh_decl = dsh_field.get("client", ABSENT)
                    else:
                        dsh_decl = ABSENT
                    if not pkg_name or dsh_decl is ABSENT:
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

        self.compose()

    def compose(self) -> Dict[str, Any]:
        """
        Compose the served graph: ordered rows, startup batches, responses.

        Rows keep the revision they already carry, so a rebuild or a newly
        mounted seam recomposes without renumbering the untouched rows.
        """
        raw_entries: List[Dict[str, Any]] = []
        table: Dict[str, Dict[str, Any]] = {}
        missing: List[MissingClientBundleError] = []
        other_failures: List[BaseException] = []
        allowed_packages = self._roster | self._dynamic_surfaces

        # Scan order is the port's composition order (the reference order is
        # the Loader's entry order). Sorting makes it deterministic on any
        # filesystem enumeration order; dependencies are still placed by
        # `order_by_module_graph`, which only reorders to satisfy edges.
        for pkg_name in sorted(self._pkg_meta):
            meta = self._pkg_meta[pkg_name]
            # Only packages on the Web App roster or an active dynamic
            # capability seam are composed into the served graph.
            if self._roster and pkg_name not in allowed_packages:
                continue

            existing = self._table.get(pkg_name)
            if existing is not None and existing["meta"] is meta:
                record = existing
            else:
                client_path = meta.get("client_path") or ""
                if meta.get("virtual"):
                    bundle = self._bundle_cache.get(pkg_name) or b""
                    record = {
                        "id": pkg_name,
                        "meta": meta,
                        "bundle": bundle,
                        "source_map": None,
                        "baseline": {"path": client_path, "mtimeMs": 0.0, "size": len(bundle)},
                    }
                else:
                    try:
                        baseline, bundle, source_map = self.initial_bundle_snapshot(pkg_name, client_path)
                    except MissingClientBundleError as error:
                        missing.append(error)
                        continue
                    except OSError as error:
                        # A bundle that exists but cannot be read is not a
                        # missing build: it is reported as an other failure.
                        other_failures.append(error)
                        continue
                    record = {
                        "id": pkg_name,
                        "meta": meta,
                        "bundle": bundle,
                        "source_map": source_map,
                        "baseline": baseline,
                    }
                record["entry"] = graph_row(pkg_name, self.allocate_initial_revision(), meta)

            self._bundle_cache[pkg_name] = record["bundle"]
            self._bundle_paths[pkg_name] = meta.get("client_path") or ""
            table[pkg_name] = record
            raw_entries.append(record["entry"])

        if missing or other_failures:
            raise ClientPackageCompositionError(list(missing) + list(other_failures))

        entries = order_by_module_graph(raw_entries)
        bootstrap = [table[plugin_id] for plugin_id in PARSER_PRELOAD_IDS if plugin_id in table]
        bootstrap_ids = {record["id"] for record in bootstrap}
        application = [
            table[entry["id"]] for entry in entries
            if entry["id"] not in bootstrap_ids and entry["id"] in table
        ]

        artifacts: List[Dict[str, Any]] = []
        for records in partition_combo_records(bootstrap):
            artifacts.append(build_batch("bootstrap", records))
        for records in partition_combo_records(application):
            artifacts.append(build_batch("application", records))

        batch_responses: Dict[str, Dict[str, Any]] = {}
        for artifact in artifacts:
            batch_responses[artifact["descriptor"]["url"]] = {
                "body": artifact["script"],
                "contentType": JAVASCRIPT_CONTENT_TYPE,
            }
            batch_responses[artifact["sourceMapUrl"]] = {
                "body": artifact["sourceMap"],
                "contentType": JSON_CONTENT_TYPE,
            }
        responses = dict(batch_responses)
        for record in table.values():
            artifact = build_combo([record], record["entry"]["rev"])
            responses[artifact["url"]] = {
                "body": artifact["script"],
                "contentType": JAVASCRIPT_CONTENT_TYPE,
            }
            responses[artifact["sourceMapUrl"]] = {
                "body": artifact["sourceMap"],
                "contentType": JSON_CONTENT_TYPE,
            }

        # One prior generation covers a request racing the recomposition that
        # replaced its URL.
        self._previous_batch_responses = self._batch_responses
        self._batch_responses = batch_responses
        self._responses = responses
        self._table = table

        batches = [artifact["descriptor"] for artifact in artifacts]
        payload = json.dumps(
            {"entries": entries, "batches": batches}, ensure_ascii=False, separators=(",", ":")
        )
        self._composed = {
            "rev": short_hash(payload.encode("utf-8")),
            "entries": entries,
            "batches": batches,
        }
        return self._composed

    def flush(self) -> Dict[str, Any]:
        """Recompose the served graph from the current scan."""
        return self.compose()

    def graph(self) -> Dict[str, Any]:
        """Return the current composed WebBootGraph (window.__DSH_BOOT__)."""
        if self._composed is None:
            self.scan_packages()
        return self._composed or {"rev": "empty", "entries": [], "batches": []}

    def rebuild_listener(self, listener: Callable[[str, str], None]) -> Callable[[], None]:
        """Subscribe to bundle rebuilds; fires only when the re-hash changed the rev."""
        self.rebuild_listeners.append(listener)

        def disposer() -> None:
            if listener in self.rebuild_listeners:
                self.rebuild_listeners.remove(listener)

        return disposer

    def artifact_baseline(self, pkg_id: str) -> Optional[Dict[str, Any]]:
        """Filesystem baseline captured before the row's current bytes were read."""
        record = self._table.get(pkg_id)
        return dict(record["baseline"]) if record is not None else None

    def rebuilt(self, pkg_id: str) -> Optional[str]:
        """
        Re-hash one bundle: the only entry point through which bundle content
        changes reach the graph. Unknown ids and unbuilt virtual seams are
        no-ops.
        """
        record = self._table.get(pkg_id)
        if record is None or record["meta"].get("virtual"):
            return None
        client_path = record["meta"].get("client_path")
        baseline = self.capture_artifact_baseline(client_path)
        with open(client_path, "rb") as handle:
            bundle = handle.read()
        source_map = self.read_source_map_snapshot(client_path)
        rev = artifact_revision(bundle, source_map)
        record["baseline"] = baseline
        if rev == record["entry"]["rev"]:
            return rev
        record["entry"] = graph_row(pkg_id, rev, record["meta"])
        record["bundle"] = bundle
        record["source_map"] = source_map
        self.compose()
        for listener in list(self.rebuild_listeners):
            try:
                listener(pkg_id, rev)
            except Exception as error:
                self._log_warn(error)
        return rev

    def client_path(self, pkg_id: str) -> Optional[str]:
        """Return the absolute path of a package's client bundle."""
        if not self._pkg_meta:
            self.scan_packages()
        return self._bundle_paths.get(pkg_id)

    def register_virtual_bundle(self, pkg_id: str, bundle_content: bytes, inject: Optional[List[str]] = None, immediately: bool = False) -> None:
        """Register an in-memory client bundle (a dynamic capability seam)."""
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
        self.compose()

    def resource_url(self, request: Dict[str, Any]) -> str:
        """
        The response key: request path plus query, exactly the resource the
        generated URLs address (upstream `pathname + search`).
        """
        raw_url = request.get("raw_url")
        if isinstance(raw_url, str) and raw_url:
            return raw_url.split("#", 1)[0]
        path = request.get("path") or "/"
        query = request.get("query") or ""
        return "%s?%s" % (path, query) if query else path

    async def handle_plugin_request(self, request: Dict[str, Any], response: HttpResponseWriter) -> None:
        """
        Serve one `/plugins` resource: a generated combo script, a combo source
        map, or an unknown resource (an empty 404). Versioned bytes are
        immutable, so the current generation and one prior generation answer;
        every other revision is rejected rather than served newer bytes.
        """
        method = request.get("method", "GET")
        if method not in ("GET", "HEAD"):
            response.write_status(405)
            await response.finish()
            return

        url = self.resource_url(request)
        entry = self._responses.get(url) or self._previous_batch_responses.get(url)
        if entry is not None:
            response.write_status(200)
            response.write_header("content-type", entry["contentType"])
            response.write_header("cache-control", IMMUTABLE_CACHE)
            if method != "HEAD":
                response.write_body(entry["body"])
            await response.finish()
            return

        response.write_status(404)
        await response.finish()

    def boot_injections(self, graph: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        The boot protocol as index injection rows.

        The inline registration queue precedes the application-batch preloads
        and the blocking bootstrap batch, and the graph global follows before
        the shell reads it.
        """
        graph = graph if graph is not None else self.graph()
        bootstrap_id = json.dumps(CLIENT_MODULES_ID)
        queue = (
            "(()=>{\n"
            "const pendingQueue=[]\n"
            "window.__ModuleLoader__={\n"
            '  mode:"queue",\n'
            "  pendingQueue,\n"
            "  load(registration){pendingQueue.push(registration)},\n"
            "  create(options){\n"
            '    if(this.mode!=="queue")throw new Error("client-modules: window.__ModuleLoader__.create called after module-system boot")\n'
            "    const index=pendingQueue.findIndex(registration=>registration.id===" + bootstrap_id + ")\n"
            "    const registration=pendingQueue[index]\n"
            '    if(registration===undefined)throw new Error("client-modules: HTML did not preload ' + CLIENT_MODULES_ID + '/client.js")\n'
            "    pendingQueue.splice(index,1)\n"
            "    const exports=registration.factory(specifier=>{\n"
            "      throw new Error('client-modules: " + CLIENT_MODULES_ID + "/client.js requested external \"'+specifier+'\" before the module system existed')\n"
            "    })\n"
            '    if(typeof exports!=="object"||exports===null||typeof exports.createClientModuleSystem!=="function"||typeof exports.apply!=="function"){\n'
            '      throw new Error("client-modules: ' + CLIENT_MODULES_ID + '/client.js did not export the bootstrap module face")\n'
            "    }\n"
            "    return exports.createClientModuleSystem(this,{id:registration.id,exports},options)\n"
            "  }\n"
            "}\n"
            "})()"
        )
        batches = graph.get("batches") or []
        bootstrap = [batch for batch in batches if batch.get("phase") == "bootstrap"]
        application = [batch for batch in batches if batch.get("phase") == "application"]
        rows: List[Dict[str, Any]] = [{"kind": "script", "placement": "head", "text": queue}]
        for batch in application:
            rows.append({"kind": "script-preload", "src": batch["url"]})
        for batch in bootstrap:
            rows.append({"kind": "script-src", "placement": "head", "src": batch["url"]})
        rows.append({"kind": "global", "name": "__DSH_BOOT__", "value": graph})
        return rows


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

        # The index rows arrive through the webserver's injection table, so a
        # subscriber reads the live graph at every emit (upstream
        # `webserver/index-inject`).
        def inject_index(table: List[Dict[str, Any]]) -> None:
            table.extend(self.registry.boot_injections())

        disposer_inject = ctx.on("webserver/index-inject", inject_index)

        if hasattr(ctx, "effect"):
            ctx.effect(lambda: disposer_route)
            if disposer_inject is not None:
                ctx.effect(lambda: disposer_inject)
