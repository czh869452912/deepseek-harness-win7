import json
import os
import tempfile
import time
import pytest
import yaml
from dsh.cordis.context import Context
from dsh.credentials.credentials_local import (
    CredentialsLocalPlugin,
    CredentialsService,
    ensure_cold_start,
)
from dsh.llm.llm_service import LLMService
from dsh.settings.settings_file import (
    SettingsConflictError,
    SettingsFilePlugin,
    SettingsService,
    patch_node,
)


def test_credentials_service(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        creds_file = os.path.join(tmpdir, "credentials.json")
        ctx = Context()
        creds = CredentialsService(ctx=ctx, credentials_file=creds_file)
        ctx.set_service("credentials", creds)

        creds.set_credential("DEEPSEEK_API_KEY", "sk-test-creds-key")
        assert creds.resolve("DEEPSEEK_API_KEY") == "sk-test-creds-key"

        monkeypatch.setenv("CUSTOM_TEST_KEY", "sk-env-key")
        assert creds.resolve("CUSTOM_TEST_KEY") == "sk-env-key"


def test_settings_service():
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_file = os.path.join(tmpdir, "settings.json")
        settings = SettingsService(settings_file=settings_file)

        settings.set_setting("llm", "base_url", "https://custom.api.endpoint")
        settings.set_setting("llm", "model", "deepseek-v4-pro")

        assert settings.get_setting("llm", "base_url") == "https://custom.api.endpoint"
        assert settings.get_setting("llm", "model") == "deepseek-v4-pro"

        settings2 = SettingsService(settings_file=settings_file)
        assert settings2.get_setting("llm", "base_url") == "https://custom.api.endpoint"


def test_llm_per_request_dynamic_resolution(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = Context()
        creds = CredentialsService(ctx=ctx, credentials_file=os.path.join(tmpdir, "credentials.json"))
        ctx.set_service("credentials", creds)

        settings = SettingsService(settings_file=os.path.join(tmpdir, "settings.json"))
        ctx.set_service("settings", settings)

        llm = LLMService(ctx=ctx)

        creds.set_credential("DEEPSEEK_API_KEY", "sk-dynamic-key-123")
        settings.set_setting("llm", "base_url", "https://dynamic.api.com")
        settings.set_setting("llm", "model", "deepseek-v4-flash")

        assert llm.resolve_api_key() == "sk-dynamic-key-123"
        assert llm.resolve_base_url() == "https://dynamic.api.com"
        assert llm.resolve_model() == "deepseek-v4-flash"


def test_cold_start_file_creation():
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_path, creds_path = ensure_cold_start(tmpdir)
        assert os.path.exists(settings_path)
        assert os.path.exists(creds_path)

        with open(settings_path, "r", encoding="utf-8") as f:
            content = f.read()
            data = yaml.safe_load(content)
            assert isinstance(data, dict)

        with open(creds_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert isinstance(data, dict)


def test_settings_update_replace_mutate_rpcs_and_events():
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_file = os.path.join(tmpdir, "settings.yaml")
        ctx = Context()
        events_received = []

        def on_updated(ns, next_val, prev_val, source):
            events_received.append(("updated", ns, next_val))

        def on_doc_updated(ns, rev):
            events_received.append(("doc_updated", ns, rev))

        ctx.on("settings/updated", on_updated)
        ctx.on("settings/document-updated", on_doc_updated)

        settings = SettingsService(ctx=ctx, settings_file=settings_file)
        scope = settings.register("llm", base={"model": "default-model", "base_url": "https://default.com"})

        watched_changes = []
        scope.watch(lambda next_v, prev_v: watched_changes.append((next_v, prev_v)))

        # 1. update
        settings.update("llm", {"model": "updated-model"})
        assert scope.get()["model"] == "updated-model"
        assert scope.get()["base_url"] == "https://default.com"
        assert settings.get_revision("llm") == 2
        assert len(watched_changes) == 1

        # 2. replace
        settings.replace("llm", {"base_url": "https://newbase.com"})
        assert scope.get()["model"] == "default-model"
        assert scope.get()["base_url"] == "https://newbase.com"
        assert settings.get_revision("llm") == 3

        # 3. mutate
        settings.mutate("llm", [
            {"op": "set", "path": ["model"], "value": "mutated-model"},
            {"op": "set", "path": ["extra", "nested"], "value": "val123"},
        ])
        assert scope.get()["model"] == "mutated-model"
        assert scope.get()["extra"]["nested"] == "val123"

        # 4. SettingsConflictError
        with pytest.raises(SettingsConflictError):
            settings.update("llm", {"model": "stale"}, expected_revision=1)

        assert any(e[0] == "updated" for e in events_received)
        assert any(e[0] == "doc_updated" for e in events_received)

        # Persistence check
        settings2 = SettingsService(ctx=Context(), settings_file=settings_file)
        assert settings2.get_section("llm")["model"] == "mutated-model"


def test_patch_node_and_reconcile_from_disk():
    doc = {"llm": {"model": "v1", "base_url": "http://v1.com"}}
    patch_node(doc, ["llm"], doc["llm"], {"model": "v2"})
    assert doc["llm"] == {"model": "v2"}

    with tempfile.TemporaryDirectory() as tmpdir:
        sf = os.path.join(tmpdir, "settings.json")
        settings = SettingsService(settings_file=sf)
        settings.set_setting("general", "theme", "light")

        # Edit disk directly
        with open(sf, "w", encoding="utf-8") as f:
            json.dump({"general": {"theme": "dark"}}, f)

        settings.reconcile_from_disk()
        assert settings.get_setting("general", "theme") == "dark"


def test_credentials_record_management():
    with tempfile.TemporaryDirectory() as tmpdir:
        creds_file = os.path.join(tmpdir, ".credentials.yaml")
        ctx = Context()
        record_events = []
        ctx.on("credentials/record-updated", lambda key: record_events.append(key))

        creds = CredentialsService(ctx=ctx, credentials_file=creds_file)
        key = "llm-pi-ai/route-1"

        assert creds.read_record(key) is None
        assert creds.describe_record(key)["configured"] is False

        # mutate / modifyRecord
        def mutate_fn(cur):
            return {"kind": "api-key", "key": "sk-record-key-99"}

        rec = creds.modify_record(key, mutate_fn)
        assert rec["kind"] == "api-key"
        assert rec["key"] == "sk-record-key-99"
        assert creds.read_record(key)["key"] == "sk-record-key-99"
        assert creds.describe_record(key)["configured"] is True
        assert len(creds.list_records()) == 1
        assert creds.list_records()[0]["key"] == key
        assert key in record_events

        # deleteRecord
        creds.delete_record(key)
        assert creds.read_record(key) is None
        assert creds.describe_record(key)["configured"] is False
        assert len(creds.list_records()) == 0
