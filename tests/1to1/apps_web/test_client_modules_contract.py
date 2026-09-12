"""
1:1 mapping of the `@deepseek-ai/dsh-client-modules` official cases
(`reference/packages/client/modules/tests/node-half.client.spec.ts`) that decide
the boot graph the served `apps/web` payload advertises.

Ported upstream cases:

  - ``places every requested package row before its consumers along a chain``
  - ``places a shared package row before both arms of a diamond``
  - ``resolves a /client request onto the requested package row``
  - ``leaves a request no row answers to the static assembly channel``
  - ``rejects a cycle and names the packages on it``
  - ``rejects a row requesting its own package name``
  - ``composes the served graph in module-graph order``
  - ``fails activation loud when scanned packages form a module cycle``
  - ``accepts external requests and carries them onto the graph row``
  - ``omits external when the package declares no requests``
  - ``rejects a non-array external``
  - ``groups missing bundles under one source-build instruction with a
    package/path list``
  - ``does not report other bundle read failures as missing builds``

Metadata validation cases mirroring `parseDshClient` / `clientExportOf`:

  - a non-object `dsh.client` declaration fails the load
  - `dsh.client.platform` must be a string
  - a row declaring `dsh.client` must export a resolvable `./client` bundle

The combo/batch tier is ported too: every row is addressed through the shared
combo route (`/plugins/??<ids>/client.js&rev=<rev>`), the graph carries the
startup batches, and the startup revisions are opaque.

Additional cases ported from the same file:

  - ``preloads every application combo``
  - ``assigns opaque startup revisions instead of deriving them from artifact content``
  - ``retains one prior immutable batch generation across rebuild recomposition``
  - ``splits startup combos before the map-form URL exceeds 3 KiB``
  - ``serves the source map beside a registered client bundle``
  - ``falls back to a generated-file map when an authored map is malformed``
  - ``maps packed combo sections back to each generated client bundle``
"""

import json
import os
import re

import pytest

from dsh.cordis.context import Context
from dsh.host.webserver.injections import render_index_injections
from dsh.host.client_modules.registry import (
    ClientModuleRegistry,
    ClientPackageCompositionError,
    order_by_module_graph,
)


def combo_url(package_id):
    return "/plugins/??%s/client.js&rev=0" % package_id


def entry(package_id, **fields):
    row = {"id": package_id, "url": combo_url(package_id), "rev": "0"}
    row.update(fields)
    return row


def ids(rows):
    return [row["id"] for row in rows]


def test_places_every_requested_package_row_before_its_consumers_along_a_chain():
    assert ids(order_by_module_graph([
        entry("ui", external=["slots"]),
        entry("slots", external=["render"]),
        entry("render"),
    ])) == ["render", "slots", "ui"]


def test_places_a_shared_package_row_before_both_arms_of_a_diamond():
    assert ids(order_by_module_graph([
        entry("app", external=["left", "right"]),
        entry("left", external=["vendor"]),
        entry("right", external=["vendor"]),
        entry("vendor"),
    ])) == ["vendor", "left", "right", "app"]


def test_resolves_a_client_request_onto_the_requested_package_row():
    assert ids(order_by_module_graph([
        entry("ui", external=["runtime/client"]),
        entry("runtime"),
    ])) == ["runtime", "ui"]


def test_leaves_a_request_no_row_answers_to_the_static_assembly_channel():
    assert ids(order_by_module_graph([
        entry("consumer", external=["@deepseek-ai/cordis"]),
        entry("other"),
    ])) == ["consumer", "other"]


def test_rejects_a_cycle_and_names_the_packages_on_it():
    with pytest.raises(ValueError) as excinfo:
        order_by_module_graph([
            entry("a", external=["b"]),
            entry("b", external=["a"]),
        ])
    assert "client-modules: module graph cycle a -> b -> a" in str(excinfo.value)


def test_rejects_a_row_requesting_its_own_package_name():
    with pytest.raises(ValueError) as excinfo:
        order_by_module_graph([entry("solo", external=["solo"])])
    assert 'client-modules: "solo" requests module "solo" that it answers itself' in str(excinfo.value)


def write_package(packages_dir, package_name, client=None, metadata=None):
    """Create one built package whose `./client` export points at its bundle."""
    package_root = os.path.join(packages_dir, package_name.replace("/", os.sep))
    client_path = os.path.join(package_root, "lib", "client.js")
    os.makedirs(os.path.dirname(client_path), exist_ok=True)
    declaration = {"platform": "web"}
    declaration.update(client or {})
    manifest = {
        "name": package_name,
        "exports": {"./client": "./lib/client.js", "./package.json": "./package.json"},
    }
    if metadata is None:
        manifest["dsh"] = {"client": declaration}
    else:
        manifest.update(metadata)
    with open(os.path.join(package_root, "package.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle)
    return client_path


def write_bundle(client_path, body="module.exports = {}\n"):
    """Write the built client bundle at `client_path` (parents must exist)."""
    with open(client_path, "w", encoding="utf-8") as handle:
        handle.write(body)


def build(packages_dir, names):
    """Compose one registry scan over exactly the named fixture packages."""
    registry = ClientModuleRegistry(Context(), search_dirs=[str(packages_dir)], roster=set(names))
    return registry


def test_composes_the_served_graph_in_module_graph_order(tmp_path):
    packages_dir = tmp_path / "packages"
    consumer = "@fixture/order-consumer"
    dependency = "@fixture/order-dependency"
    write_bundle(write_package(packages_dir, consumer, client={"external": [dependency]}))
    write_bundle(write_package(packages_dir, dependency))
    registry = build(packages_dir, [consumer, dependency])
    assert ids(registry.graph()["entries"]) == [dependency, consumer]


def test_fails_activation_loud_when_scanned_packages_form_a_module_cycle(tmp_path):
    packages_dir = tmp_path / "packages"
    first, second = "@fixture/cycle-a", "@fixture/cycle-b"
    write_bundle(write_package(packages_dir, first, client={"external": [second]}))
    write_bundle(write_package(packages_dir, second, client={"external": [first]}))
    registry = build(packages_dir, [first, second])
    with pytest.raises(ValueError) as excinfo:
        registry.graph()
    assert "module graph cycle %s -> %s -> %s" % (first, second, first) in str(excinfo.value)


def test_accepts_external_requests_and_carries_them_onto_the_graph_row(tmp_path):
    packages_dir = tmp_path / "packages"
    name = "@fixture/shared-declared"
    write_bundle(write_package(packages_dir, name, client={"external": ["react"]}))
    rows = build(packages_dir, [name]).graph()["entries"]
    assert rows[0]["id"] == name
    assert rows[0]["external"] == ["react"]
    assert rows[0]["url"] == "/plugins/??%s/client.js&rev=%s" % (name, rows[0]["rev"])
    assert rows[0]["rev"]


def test_omits_external_when_the_package_declares_no_requests(tmp_path):
    packages_dir = tmp_path / "packages"
    name = "@fixture/shared-absent"
    write_bundle(write_package(packages_dir, name))
    rows = build(packages_dir, [name]).graph()["entries"]
    assert "external" not in rows[0]


def test_rejects_a_non_array_external(tmp_path):
    packages_dir = tmp_path / "packages"
    name = "@fixture/external-not-array"
    write_bundle(write_package(packages_dir, name, client={"external": "react"}))
    with pytest.raises(ValueError) as excinfo:
        build(packages_dir, [name]).graph()
    assert str(excinfo.value) == "client-modules: %s dsh.client.external must be a string array" % name


def test_groups_missing_bundles_under_one_source_build_instruction_with_a_package_path_list(tmp_path):
    packages_dir = tmp_path / "packages"
    first, second = "@fixture/missing-first", "@fixture/missing-second"
    first_path = write_package(packages_dir, first)
    second_path = write_package(packages_dir, second)
    with pytest.raises(ClientPackageCompositionError) as excinfo:
        build(packages_dir, [first, second]).graph()
    message = str(excinfo.value)
    lines = message.split("\n")
    assert lines[0] == "client-modules: 2 client packages failed to compose:"
    assert lines[1] == "  client bundles not found; run `pnpm run build` before launch:"
    assert "    - package: %s\n      path: %s" % (first, first_path) in message
    assert "    - package: %s\n      path: %s" % (second, second_path) in message
    assert "other failures" not in message


def test_does_not_report_other_bundle_read_failures_as_missing_builds(tmp_path):
    packages_dir = tmp_path / "packages"
    name = "@fixture/unreadable-client"
    client_path = write_package(packages_dir, name)
    os.makedirs(client_path)
    with pytest.raises(ClientPackageCompositionError) as excinfo:
        build(packages_dir, [name]).graph()
    message = str(excinfo.value)
    assert "client-modules: 1 client package failed to compose:" in message
    assert "  other failures:" in message
    assert "EISDIR" in message
    assert "pnpm run build" not in message


def test_rejects_a_non_object_dsh_client_declaration(tmp_path):
    packages_dir = tmp_path / "packages"
    name = "@fixture/non-object-declaration"
    write_package(packages_dir, name, metadata={"dsh": {"client": "web"}})
    with pytest.raises(ValueError) as excinfo:
        build(packages_dir, [name]).graph()
    assert str(excinfo.value) == "client-modules: %s has a non-object dsh.client declaration" % name


def test_requires_a_string_dsh_client_platform(tmp_path):
    packages_dir = tmp_path / "packages"
    name = "@fixture/platform-not-string"
    write_package(packages_dir, name, metadata={"dsh": {"client": {"platform": 7}}})
    with pytest.raises(ValueError) as excinfo:
        build(packages_dir, [name]).graph()
    assert str(excinfo.value) == "client-modules: %s dsh.client.platform must be a string" % name


def test_requires_a_resolvable_client_export(tmp_path):
    packages_dir = tmp_path / "packages"
    name = "@fixture/no-client-export"
    client_path = write_package(packages_dir, name)
    os.makedirs(os.path.dirname(client_path), exist_ok=True)
    manifest_path = os.path.join(str(packages_dir), name.replace("/", os.sep), "package.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump({"name": name, "exports": {"./package.json": "./package.json"}, "dsh": {"client": {"platform": "web"}}}, handle)
    with pytest.raises(ValueError) as excinfo:
        build(packages_dir, [name]).graph()
    assert str(excinfo.value) == 'client-modules: %s declares dsh.client but exports no "./client" bundle' % name


# ---------------------------------------------------------------------------
# Combo / batch / source-map tier
# ---------------------------------------------------------------------------

MODULES_ID = "@deepseek-ai/dsh-client-modules"
UI_RENDERER_ID = "@deepseek-ai/dsh-client-ui-renderer"


def boot_graph_fixture():
    """The reference `bootGraph()` fixture: one bootstrap, one application row."""
    return {
        "rev": "graph",
        "entries": [
            {"id": MODULES_ID, "url": "/plugins/??%s/client.js&rev=m" % MODULES_ID, "rev": "m"},
            {"id": UI_RENDERER_ID, "url": "/plugins/??%s/client.js&rev=r" % UI_RENDERER_ID, "rev": "r"},
        ],
        "batches": [
            {
                "phase": "bootstrap",
                "url": "/plugins/??%s/client.js&rev=boot" % MODULES_ID,
                "rev": "boot",
                "entries": [MODULES_ID],
            },
            {
                "phase": "application",
                "url": "/plugins/??%s/client.js&rev=app" % UI_RENDERER_ID,
                "rev": "app",
                "entries": [UI_RENDERER_ID],
            },
        ],
    }


def combo_map_url(url):
    """`mapUrl(url)`: the source-map resource beside one combo script URL."""
    return re.sub(r"/client\.js(?=,|&rev=)", "/client.js.map", url)


async def route_request(registry, url, method="GET"):
    """Invoke the registered `/plugins` route and capture status, headers, bytes."""
    path, _, query = url.partition("?")
    request = {
        "method": method,
        "path": path,
        "query": query,
        "raw_url": url,
        "headers": {},
        "body": b"",
    }
    response = RecordingResponse()
    await registry.handle_plugin_request(request, response)
    return response


class RecordingResponse:
    """Minimal response recorder standing in for the socket writer."""

    def __init__(self):
        self.status = 0
        self.headers = {}
        self.body = bytearray()

    def write_status(self, status):
        self.status = status

    def write_header(self, key, value):
        self.headers[key.lower()] = value

    def write_body(self, data):
        self.body.extend(data)

    async def finish(self):
        pass


def source_at(section_maps, line):
    """
    The original source a standard consumer resolves for one generated line.

    The port carries no JavaScript VM, so this minimal reader walks the indexed
    map the same way `node:module`'s SourceMap does for the fixtures here: the
    last section whose offset precedes the line owns it, and that section's
    segment at the local line names source 0.
    """
    for index in range(len(section_maps) - 1, -1, -1):
        section = section_maps[index]
        if section["offset"]["line"] > line:
            continue
        local = line - section["offset"]["line"]
        lines = section["map"]["mappings"].split(";")
        if local < len(lines) and lines[local]:
            return section["map"]["sources"][0]
        return None
    return None


def test_preloads_every_application_combo():
    """One preload row per application batch, in batch order."""
    graph = boot_graph_fixture()
    second_id = "@fixture/second-application-combo"
    second_url = "/plugins/??%s/client.js&rev=app-2" % second_id
    graph["entries"].append({
        "id": second_id,
        "url": "/plugins/??%s/client.js&rev=row-2" % second_id,
        "rev": "row-2",
    })
    graph["batches"].append({
        "phase": "application",
        "url": second_url,
        "rev": "app-2",
        "entries": [second_id],
    })
    rows = ClientModuleRegistry(Context()).boot_injections(graph)
    assert [row["src"] for row in rows if row["kind"] == "script-preload"] == [
        graph["batches"][1]["url"],
        second_url,
    ]


def test_boot_rows_precede_the_shell_and_the_graph_global():
    """Facade, application preload, bootstrap script, graph global, then shell."""
    graph = boot_graph_fixture()
    rows = ClientModuleRegistry(Context()).boot_injections(graph)
    html = render_index_injections(
        '<html><head></head><body><script type="module" src="/index.js"></script></body></html>',
        rows,
    )
    facade_at = html.index("window.__ModuleLoader__={")
    application_at = html.index(
        '<link rel="preload" as="script" href="%s">' % graph["batches"][1]["url"].replace("&", "&amp;")
    )
    bootstrap_at = html.index(
        '<script src="%s"></script>' % graph["batches"][0]["url"].replace("&", "&amp;")
    )
    graph_at = html.index('globalThis["__DSH_BOOT__"] = ')
    entry_at = html.index('<script type="module" src="/index.js"></script>')
    assert [facade_at, application_at, bootstrap_at, graph_at, entry_at] == sorted(
        [facade_at, application_at, bootstrap_at, graph_at, entry_at]
    )


def test_assigns_opaque_startup_revisions_instead_of_deriving_them_from_artifact_content(tmp_path):
    packages_dir = tmp_path / "packages"
    first_name, second_name = "@fixture/startup-revision-first", "@fixture/startup-revision-second"
    first_path = write_package(packages_dir, first_name)
    second_path = write_package(packages_dir, second_name)
    write_bundle(first_path)
    write_bundle(second_path)
    registry = build(packages_dir, [first_name, second_name])
    first, second = registry.graph()["entries"]

    pattern = re.compile(r"^[0-9a-f]{16}-(\d+)$")
    first_match = pattern.match(first["rev"])
    second_match = pattern.match(second["rev"])
    assert first_match is not None and first_match.group(1) == "0"
    assert second_match is not None
    assert second_match.group(1) == "1"
    assert second_match.group(0).split("-")[0] == first_match.group(0).split("-")[0]

    first_stat = os.stat(first_path)
    assert registry.artifact_baseline(first_name) == {
        "path": first_path,
        "mtimeMs": first_stat.st_mtime * 1000.0,
        "size": first_stat.st_size,
    }
    assert registry.artifact_baseline("@fixture/unknown") is None


def test_serves_the_source_map_beside_a_registered_client_bundle(tmp_path):
    import asyncio

    packages_dir = tmp_path / "packages"
    name = "@fixture/source-map"
    client_path = write_package(packages_dir, name)
    write_bundle(client_path, "module.exports = {}\n//# sourceMappingURL=client.js.map")
    authored = (
        '{"version":3,"names":[],"mappings":"AAAA","sources":'
        '["../../../packages/client/demo/src/index.tsx","https://cdn.example.test/library.js"]}\n'
    )
    with open(client_path + ".map", "w", encoding="utf-8") as handle:
        handle.write(authored)

    registry = build(packages_dir, [name])
    graph = registry.graph()
    row = graph["entries"][0]

    single_script = asyncio.run(route_request(registry, row["url"]))
    assert ("sourceMappingURL=%s" % combo_map_url(row["url"])) in single_script.body.decode("utf-8")

    single_map = asyncio.run(
        route_request(registry, combo_map_url(row["url"]))
    )
    assert single_map.status == 200
    assert single_map.headers == {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "public, max-age=31536000, immutable",
    }
    parsed = json.loads(single_map.body.decode("utf-8"))
    assert parsed["version"] == 3
    assert parsed["file"] == "client.js"
    assert parsed["sections"][0]["offset"] == {"line": 0, "column": 0}
    assert parsed["sections"][0]["map"]["sources"] == [
        "/packages/client/demo/src/index.tsx",
        "https://cdn.example.test/library.js",
    ]

    batch = graph["batches"][0]
    assert batch["phase"] == "application"
    assert batch["entries"] == [name]
    batch_script = asyncio.run(route_request(registry, batch["url"]))
    assert batch_script.status == 200
    assert batch_script.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert ("//# sourceMappingURL=%s" % combo_map_url(batch["url"])) in batch_script.body.decode("utf-8")
    assert asyncio.run(
        route_request(registry, batch["url"], "HEAD")
    ).body == b""
    assert asyncio.run(
        route_request(registry, batch["url"], "POST")
    ).status == 405

    batch_map = json.loads(
        asyncio.run(
            route_request(registry, combo_map_url(batch["url"]))
        ).body.decode("utf-8")
    )
    assert batch_map["sections"][0]["offset"] == {"line": 0, "column": 0}
    assert batch_map["sections"][0]["map"]["sources"] == [
        "/packages/client/demo/src/index.tsx",
        "https://cdn.example.test/library.js",
    ]

    stale = row["url"].replace("rev=%s" % row["rev"], "rev=stale")
    assert asyncio.run(route_request(registry, stale)).status == 404

    # A rebuilt bundle: the row's rev changes and the new map is served beside it.
    with open(client_path + ".map", "w", encoding="utf-8") as handle:
        handle.write('{"version":3,"names":[],"mappings":"AAAA","sources":["src/changed.tsx"]}\n')
    next_rev = registry.rebuilt(name)
    assert next_rev != row["rev"]
    next_row = registry.graph()["entries"][0]
    assert next_row["rev"] == next_rev
    next_map = json.loads(
        asyncio.run(
            route_request(registry, combo_map_url(next_row["url"]))
        ).body.decode("utf-8")
    )
    assert next_map["sections"][0]["map"]["sources"] == ["/plugins/%s/src/changed.tsx" % name]


def test_retains_one_prior_immutable_batch_generation_across_rebuild_recomposition(tmp_path):
    import asyncio

    packages_dir = tmp_path / "packages"
    name = "@fixture/batch-rebuild-race"
    client_path = write_package(packages_dir, name)
    write_bundle(client_path, "module.exports = { generation: 1 }\n")
    registry = build(packages_dir, [name])
    first = registry.graph()["batches"][0]["url"]
    first_size = registry.artifact_baseline(name)["size"]

    write_bundle(client_path, "module.exports = { generation: 200 }\n")
    registry.rebuilt(name)
    second = registry.graph()["batches"][0]["url"]
    assert second != first
    assert registry.artifact_baseline(name)["size"] > first_size
    assert asyncio.run(route_request(registry, first)).status == 200
    assert asyncio.run(route_request(registry, second)).status == 200

    write_bundle(client_path, "module.exports = { generation: 3 }\n")
    registry.rebuilt(name)
    third = registry.graph()["batches"][0]["url"]
    assert asyncio.run(route_request(registry, first)).status == 404
    assert asyncio.run(route_request(registry, second)).status == 200
    assert asyncio.run(route_request(registry, third)).status == 200


def test_splits_startup_combos_before_the_map_form_url_exceeds_three_kib(tmp_path):
    import asyncio

    packages_dir = tmp_path / "packages"
    names = [
        "@fixture/combo-url-%03d-%s" % (index, "x" * 40) for index in range(48)
    ]
    source_map = json.dumps({"version": 3, "names": [], "mappings": "AAAA", "sources": ["src/index.ts"]})
    for name in names:
        client_path = write_package(packages_dir, name)
        write_bundle(client_path)
        with open(client_path + ".map", "w", encoding="utf-8") as handle:
            handle.write(source_map)

    registry = build(packages_dir, names)
    batches = [batch for batch in registry.graph()["batches"] if batch["phase"] == "application"]
    assert len(batches) > 1
    assert [entry for batch in batches for entry in batch["entries"]] == names
    for batch in batches:
        assert len(batch["url"].encode("utf-8")) <= 3 * 1024
        assert len(combo_map_url(batch["url"]).encode("utf-8")) <= 3 * 1024
        assert asyncio.run(
            route_request(registry, batch["url"])
        ).status == 200
        assert asyncio.run(
            route_request(registry, combo_map_url(batch["url"]))
        ).status == 200
    for index in range(len(batches) - 1):
        entries = list(batches[index]["entries"]) + [batches[index + 1]["entries"][0]]
        joined = "/plugins/??%s&rev=%s" % (
            ",".join("%s/client.js.map" % entry for entry in entries),
            "0" * 12,
        )
        assert len(joined.encode("utf-8")) > 3 * 1024


def test_falls_back_to_a_generated_file_map_when_an_authored_map_is_malformed(tmp_path):
    import asyncio

    packages_dir = tmp_path / "packages"
    name = "@fixture/malformed-source-map"
    client_path = write_package(packages_dir, name)
    write_bundle(client_path, "module.exports = {}\n")
    with open(client_path + ".map", "w", encoding="utf-8") as handle:
        handle.write("{")
    registry = build(packages_dir, [name])
    row = registry.graph()["entries"][0]
    script = asyncio.run(route_request(registry, row["url"]))
    assert ("sourceMappingURL=%s" % combo_map_url(row["url"])) in script.body.decode("utf-8")
    fallback = json.loads(
        asyncio.run(
            route_request(registry, combo_map_url(registry.graph()["batches"][0]["url"]))
        ).body.decode("utf-8")
    )
    assert fallback["sections"][0]["map"]["sources"] == ["/plugins/%s/client.js" % name]

    # A torn map never fails the composition.
    with open(client_path + ".map", "w", encoding="utf-8") as handle:
        handle.write('{"version":3,"sources":[null]}\n')
    build(packages_dir, [name])


def test_maps_packed_combo_sections_back_to_each_generated_client_bundle(tmp_path):
    import asyncio

    packages_dir = tmp_path / "packages"
    names = ["@fixture/generated-first", "@fixture/generated-second"]
    for index, name in enumerate(names):
        client_path = write_package(packages_dir, name)
        write_bundle(
            client_path,
            "window.generation = %d\n//# sourceURL=packages/client/generated-%d/lib/client.js"
            % (index, index),
        )
    registry = build(packages_dir, names)
    batch = registry.graph()["batches"][0]
    script = asyncio.run(
        route_request(registry, batch["url"])
    ).body.decode("utf-8")
    assert "//# sourceURL=" not in script
    assert ("//# sourceMappingURL=%s" % combo_map_url(batch["url"])) in script
    payload = json.loads(
        asyncio.run(
            route_request(registry, combo_map_url(batch["url"]))
        ).body.decode("utf-8")
    )
    assert [section["map"] for section in payload["sections"]] == [
        {
            "version": 3,
            "names": [],
            "mappings": "AAAA",
            "sources": ["/packages/client/generated-0/lib/client.js"],
            "sourcesContent": ["window.generation = 0\n"],
        },
        {
            "version": 3,
            "names": [],
            "mappings": "AAAA",
            "sources": ["/packages/client/generated-1/lib/client.js"],
            "sourcesContent": ["window.generation = 1\n"],
        },
    ]
    assert source_at(payload["sections"], 0) == "/packages/client/generated-0/lib/client.js"
    assert source_at(payload["sections"], 2) == "/packages/client/generated-1/lib/client.js"


def test_applies_source_root_before_relocating_absolute_looking_section_sources(tmp_path):
    import asyncio

    packages_dir = tmp_path / "packages"
    name = "@fixture/source-root"
    client_path = write_package(packages_dir, name)
    write_bundle(client_path)
    with open(client_path + ".map", "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "version": 3,
            "names": [],
            "mappings": "AAAA",
            "sourceRoot": "../root",
            "sources": ["/absolute.ts"],
        }))
    registry = build(packages_dir, [name])
    section = json.loads(
        asyncio.run(
            route_request(registry, combo_map_url(registry.graph()["batches"][0]["url"]))
        ).body.decode("utf-8")
    )["sections"][0]["map"]
    assert section["sources"] == ["/plugins/@fixture/root/absolute.ts"]
    assert "sourceRoot" not in section


def test_maps_a_non_zero_second_batch_section_through_a_standard_source_map_consumer(tmp_path):
    import asyncio

    packages_dir = tmp_path / "packages"
    fixtures = [
        ("@fixture/a-offset-first", "../../../packages/demo/first.ts"),
        ("@fixture/b-offset-second", "../../../packages/demo/second.ts"),
    ]
    for name, source in fixtures:
        client_path = write_package(packages_dir, name)
        write_bundle(client_path, "window.first = true\nwindow.second = true\n")
        with open(client_path + ".map", "w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "version": 3,
                "names": [],
                "mappings": "AAAA",
                "sources": [source],
                "sourcesContent": ["export {}\n"],
            }))
    registry = build(packages_dir, [name for name, _ in fixtures])
    payload = json.loads(
        asyncio.run(
            route_request(registry, combo_map_url(registry.graph()["batches"][0]["url"]))
        ).body.decode("utf-8")
    )
    assert [section["offset"] for section in payload["sections"]] == [
        {"line": 0, "column": 0},
        {"line": 3, "column": 0},
    ]
    assert source_at(payload["sections"], 0) == "/packages/demo/first.ts"
    assert source_at(payload["sections"], 3) == "/packages/demo/second.ts"


def test_combines_a_generated_file_fallback_with_a_later_authored_map(tmp_path):
    import asyncio

    packages_dir = tmp_path / "packages"
    unmapped_name, mapped_name = "@fixture/a-unmapped-first", "@fixture/b-mapped-second"
    unmapped_path = write_package(packages_dir, unmapped_name)
    mapped_path = write_package(packages_dir, mapped_name)
    write_bundle(unmapped_path, "window.unmapped = true\n")
    write_bundle(mapped_path, "window.mapped = true\n")
    with open(mapped_path + ".map", "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "version": 3,
            "names": [],
            "mappings": "AAAA",
            "sources": ["../../../packages/demo/mapped.ts"],
            "sourcesContent": ["export {}\n"],
        }))
    registry = build(packages_dir, [unmapped_name, mapped_name])
    payload = json.loads(
        asyncio.run(
            route_request(registry, combo_map_url(registry.graph()["batches"][0]["url"]))
        ).body.decode("utf-8")
    )
    assert source_at(payload["sections"], 0) == "/plugins/%s/client.js" % unmapped_name
    assert source_at(payload["sections"], 2) == "/packages/demo/mapped.ts"
