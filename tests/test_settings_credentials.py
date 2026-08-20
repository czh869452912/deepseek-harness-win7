import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.credentials.credentials_local import CredentialsLocalPlugin, CredentialsService
from dsh.llm.llm_service import LLMService
from dsh.settings.settings_file import SettingsFilePlugin, SettingsService


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
