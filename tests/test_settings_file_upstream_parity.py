import json
import os
import threading
import time

import pytest
import yaml

from dsh.cordis.context import Context
from dsh.settings.settings_file import (
    FileSettingsProvider, SettingsFilePlugin, _WriterLock, resolve_spec,
)


def _schema(value):
    result = {"theme": "dark", "fontSize": 14}
    if isinstance(value, dict):
        result.update(value)
    return result


def _wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    assert predicate()


def _provider(path, **config):
    value = {"path": str(path), "watch": False}
    value.update(config)
    return FileSettingsProvider(ctx=Context(), config=value)


def test_resolve_spec_uses_exact_home_default_and_validates_config(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_HOME", str(tmp_path))
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    spec = resolve_spec({})
    assert spec.filename == os.path.abspath(str(tmp_path / "settings.yaml"))
    assert spec.watch is True and spec.debounce_ms == 100
    with pytest.raises(ValueError, match="extension"):
        resolve_spec({"path": str(tmp_path / "settings.txt")})
    with pytest.raises(ValueError, match="debounceMs"):
        resolve_spec({"path": str(tmp_path / "settings.yaml"), "debounceMs": -1})
    with pytest.raises(TypeError, match="watch"):
        resolve_spec({"path": str(tmp_path / "settings.yaml"), "watch": "no"})


def test_missing_file_is_a_cold_start_until_prepare_document(tmp_path):
    path = tmp_path / "nested" / "settings.yaml"
    provider = _provider(path)
    assert not path.exists()
    scope = provider.register("ui-theme", schema=_schema)
    assert scope.get() == {"theme": "dark", "fontSize": 14}
    assert provider.prepare_document() == str(path)
    assert path.read_text(encoding="utf-8") == ""
    assert provider.prepare_document() == str(path)
    assert path.read_text(encoding="utf-8") == ""
    assert not (tmp_path / "nested" / "settings.yaml.lock").exists()


@pytest.mark.parametrize("name, contents, message", [
    ("settings.yaml", "ui: [unclosed\n", "invalid document"),
    ("settings.json", "{broken", "invalid document"),
    ("settings.yaml", "- not\n- a-map\n", "map of namespace sections"),
])
def test_initial_load_fails_loud_for_invalid_existing_document(tmp_path, name, contents, message):
    path = tmp_path / name
    path.write_text(contents, encoding="utf-8")
    with pytest.raises((TypeError, ValueError), match=message):
        _provider(path)
    assert path.read_text(encoding="utf-8") == contents


def test_yaml_update_preserves_comments_unknown_sections_and_changed_key_comment(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "# personal settings\nui-theme:\n  # chosen during onboarding\n"
        "  theme: light\n  fontSize: 12\n# unloaded plugin\nfuture:\n  keep: me\n",
        encoding="utf-8",
    )
    provider = _provider(path)
    scope = provider.register("ui-theme", schema=_schema)
    scope.update({"fontSize": 18})
    text = path.read_text(encoding="utf-8")
    assert "# personal settings" in text
    assert "# chosen during onboarding" in text
    assert "# unloaded plugin" in text and "keep: me" in text
    assert "theme: light" in text and "fontSize: 18" in text
    scope.replace({"theme": "dark"})
    text = path.read_text(encoding="utf-8")
    assert "# chosen during onboarding" in text and "theme: dark" in text
    assert "fontSize" not in text


def test_yaml_unchanged_array_comment_survives_but_changed_array_replaces_it(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "workspace:\n  tags:\n    # pinned by hand\n    - alpha\n  label: draft\n",
        encoding="utf-8",
    )
    provider = _provider(path)
    scope = provider.register("workspace")
    scope.update({"label": "final"})
    assert "# pinned by hand" in path.read_text(encoding="utf-8")
    scope.update({"tags": ["beta"]})
    text = path.read_text(encoding="utf-8")
    assert "# pinned by hand" not in text
    assert "- beta" in text


def test_comment_only_yaml_keeps_comment_when_first_section_is_written(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("# reserved for future settings\n", encoding="utf-8")
    provider = _provider(path)
    scope = provider.register("ui-theme", schema=_schema)
    scope.update({"theme": "light"})
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# reserved for future settings\n")
    assert "theme: light" in text


def test_yaml_quoted_leaf_key_is_updated_without_duplication(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "editor:\n  # keep quoted key\n  'font size': 12\n",
        encoding="utf-8",
    )
    provider = _provider(path)
    scope = provider.register("editor")
    scope.update({"font size": 18})
    text = path.read_text(encoding="utf-8")
    assert "# keep quoted key" in text
    assert yaml.safe_load(text) == {"editor": {"font size": 18}}


def test_json_write_reconciles_unobserved_external_sections_and_is_atomic(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"alpha": {"value": 1}}), encoding="utf-8")
    provider = _provider(path)
    beta = provider.register("beta")
    path.write_text(json.dumps({"alpha": {"value": 8}}), encoding="utf-8")
    beta.update({"value": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "alpha": {"value": 8}, "beta": {"value": 2},
    }
    assert not path.with_suffix(".json.lock").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_write_fails_loud_on_unobserved_invalid_document_and_releases_lock(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("alpha:\n  value: 1\n", encoding="utf-8")
    provider = _provider(path)
    scope = provider.register("alpha")
    broken = "alpha: [unclosed\n"
    path.write_text(broken, encoding="utf-8")
    with pytest.raises(ValueError, match="invalid document"):
        scope.update({"value": 2})
    assert path.read_text(encoding="utf-8") == broken
    assert not (tmp_path / "settings.yaml.lock").exists()


def test_cross_instance_writes_keep_both_namespaces(tmp_path):
    path = tmp_path / "settings.yaml"
    first = _provider(path)
    second = _provider(path)
    alpha = first.register("alpha")
    beta = second.register("beta")
    failures = []

    def write(scope, name):
        try:
            for value in range(1, 6):
                scope.update({"value": value})
        except Exception as error:
            failures.append((name, error))

    threads = [threading.Thread(target=write, args=(alpha, "alpha")),
               threading.Thread(target=write, args=(beta, "beta"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document == {"alpha": {"value": 5}, "beta": {"value": 5}}


def test_refresh_keeps_last_good_then_recovers_and_removal_publishes_empty(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("ui-theme:\n  theme: light\n", encoding="utf-8")
    provider = _provider(path)
    scope = provider.register("ui-theme", schema=_schema)
    path.write_text("ui-theme: [unclosed\n", encoding="utf-8")
    provider.refresh()
    assert scope.get()["theme"] == "light"
    path.write_text("ui-theme:\n  theme: dark\n", encoding="utf-8")
    provider.refresh()
    assert scope.get()["theme"] == "dark"
    path.unlink()
    provider.refresh()
    assert scope.get() == {"theme": "dark", "fontSize": 14}


def test_watcher_publishes_external_change_suppresses_self_write_and_stops(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("ui-theme:\n  theme: light\n", encoding="utf-8")
    ctx = Context()
    events = []
    ctx.on("settings/updated", lambda ns, _next, _prev, source: events.append((ns, source)))
    provider = FileSettingsProvider(ctx=ctx, config={"path": str(path), "debounceMs": 10})
    scope = provider.register("ui-theme", schema=_schema)
    path.write_text("ui-theme:\n  theme: dark\n", encoding="utf-8")
    _wait_for(lambda: scope.get()["theme"] == "dark")
    before = len(events)
    scope.update({"fontSize": 20})
    time.sleep(0.15)
    assert len(events) == before + 1
    provider.close()
    path.write_text("ui-theme:\n  theme: light\n", encoding="utf-8")
    time.sleep(0.1)
    assert scope.get()["theme"] == "dark"


@pytest.mark.asyncio
async def test_plugin_registration_and_effect_cleanup(tmp_path):
    path = tmp_path / "settings.yaml"
    ctx = Context()
    fiber = ctx.registry.plugin(
        SettingsFilePlugin, config={"path": str(path), "watch": True, "debounceMs": 5},
        parent_ctx=ctx,
    )
    await fiber
    service = ctx.get("settings")
    assert service is not None and service.document_path == str(path)
    await fiber.dispose()
    assert service._closed is True


def test_yaml_flow_map_update_stays_valid_and_preserves_unknown_text(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "# document comment\nui: {theme: light, fontSize: 12} # flow comment\n"
        "future:\n  keep: me\n",
        encoding="utf-8",
    )
    provider = _provider(path)
    scope = provider.register("ui")

    scope.update({"fontSize": 18})

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text) == {
        "ui": {"theme": "light", "fontSize": 18},
        "future": {"keep": "me"},
    }
    assert "# document comment" in text
    assert "# flow comment" in text
    assert "future:\n  keep: me" in text


def test_yaml_direct_alias_update_rewrites_only_affected_namespace_validly(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "base: &base\n  theme: light\nui: *base\nfuture:\n  keep: me\n",
        encoding="utf-8",
    )
    provider = _provider(path)
    scope = provider.register("ui")

    scope.update({"theme": "dark"})

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text) == {
        "base": {"theme": "light"},
        "ui": {"theme": "dark"},
        "future": {"keep": "me"},
    }
    assert "base: &base\n  theme: light" in text
    assert "future:\n  keep: me" in text


def test_yaml_merge_alias_remains_valid_during_sibling_update(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        "base: &base\n  theme: light\nui:\n  <<: *base\n  fontSize: 12\n",
        encoding="utf-8",
    )
    provider = _provider(path)
    scope = provider.register("ui")

    scope.update({"fontSize": 18})

    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text)["ui"] == {"theme": "light", "fontSize": 18}
    assert "base: &base" in text
    assert "<<: *base" in text


def test_yaml_duplicate_key_fails_loud_with_position(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("ui:\n  theme: light\n  theme: dark\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"invalid document.*line 3, column 3"):
        _provider(path)


def test_explicit_dsh_home_expands_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    spec = resolve_spec({"dshHome": "~/custom-dsh", "watch": False})

    assert spec.filename == os.path.abspath(
        os.path.join(str(tmp_path), "custom-dsh", "settings.yaml"))


def test_writer_lock_uses_pinned_default_timeout(tmp_path):
    lock = _WriterLock(str(tmp_path / "settings.yaml.lock"))
    assert lock.timeout == 2.0


def test_close_joins_watcher_without_a_timeout(tmp_path):
    provider = _provider(tmp_path / "settings.yaml")

    class JoinProbe:
        def __init__(self):
            self.timeout = "not-called"

        def join(self, timeout=None):
            self.timeout = timeout

    probe = JoinProbe()
    provider._thread = probe

    provider.close()

    assert probe.timeout is None


def test_close_waits_for_an_inflight_document_operation(tmp_path):
    provider = _provider(tmp_path / "settings.yaml")
    operation_started = threading.Event()
    release_operation = threading.Event()
    close_finished = threading.Event()

    def hold_operation():
        with provider._operation_lock:
            operation_started.set()
            release_operation.wait(2)

    operation = threading.Thread(target=hold_operation)
    operation.start()
    assert operation_started.wait(1)

    closing = threading.Thread(
        target=lambda: (provider.close(), close_finished.set()))
    closing.start()
    assert not close_finished.wait(0.1)

    release_operation.set()
    operation.join(1)
    closing.join(1)
    assert close_finished.is_set()
