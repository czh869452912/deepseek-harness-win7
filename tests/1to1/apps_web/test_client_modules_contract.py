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

Not ported: the combo/batch tier (`/plugins/??<ids>&rev=`, source-map packing,
opaque startup revisions) is a recorded gap — this port advertises one
`/plugins/<id>/client.js?rev=<sha1>` row per entry.
"""

import json
import os

import pytest

from dsh.cordis.context import Context
from dsh.host.client_modules.registry import (
    ClientModuleRegistry,
    ClientPackageCompositionError,
    order_by_module_graph,
)


def combo_url(package_id):
    return "/plugins/%s/client.js?rev=0" % package_id


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
    assert "/plugins/%s/client.js?rev=" % name in rows[0]["url"]
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
