import os
import tempfile
import pytest
from dsh.cordis.context import Context
from dsh.plugins.credentials_local import CredentialsLocalPlugin
from dsh.plugins.settings_file import SettingsFilePlugin
from dsh.services.credentials import CredentialsService
from dsh.services.llm import LLMService
from dsh.services.settings import SettingsService


def test_credentials_service():
    ctx = Context()
    creds = CredentialsService(ctx=ctx)
    ctx.set_service("credentials", creds)

    # 1. Store credential
    creds.set_credential("DEEPSEEK_API_KEY", "sk-test-creds-key")
    assert creds.resolve("DEEPSEEK_API_KEY") == "sk-test-creds-key"

    # 2. Environment fallback
    os.environ["CUSTOM_TEST_KEY"] = "sk-env-key"
    assert creds.resolve("CUSTOM_TEST_KEY") == "sk-env-key"


def test_settings_service():
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_file = os.path.join(tmpdir, "settings.json")
        settings = SettingsService(settings_file=settings_file)

        settings.set_setting("llm", "base_url", "https://custom.api.endpoint")
        settings.set_setting("llm", "model", "deepseek-v4-pro")

        assert settings.get_setting("llm", "base_url") == "https://custom.api.endpoint"
        assert settings.get_setting("llm", "model") == "deepseek-v4-pro"

        # Test reload from file
        settings2 = SettingsService(settings_file=settings_file)
        assert settings2.get_setting("llm", "base_url") == "https://custom.api.endpoint"


def test_llm_per_request_dynamic_resolution():
    ctx = Context()
    creds = CredentialsService(ctx=ctx)
    ctx.set_service("credentials", creds)

    with tempfile.TemporaryDirectory() as tmpdir:
        settings = SettingsService(settings_file=os.path.join(tmpdir, "settings.json"))
        ctx.set_service("settings", settings)

        llm = LLMService(ctx=ctx)

        # 1. Set credentials & settings dynamically
        creds.set_credential("DEEPSEEK_API_KEY", "sk-dynamic-key-123")
        settings.set_setting("llm", "base_url", "https://dynamic.api.com")
        settings.set_setting("llm", "model", "deepseek-v4-flash")

        assert llm.resolve_api_key() == "sk-dynamic-key-123"
        assert llm.resolve_base_url() == "https://dynamic.api.com"
        assert llm.resolve_model() == "deepseek-v4-flash"
