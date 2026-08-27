import os
import tempfile
import pytest

from dsh.cordis.context import Context
from dsh.cordis.environment import (
    resolve_dsh_home,
    parse_dotenv,
    is_bootstrap_only,
    load_layered_env,
    LaunchEnvironmentSnapshot,
    resolve_layered_config,
)
from dsh.credentials.credentials_local import CredentialsService
from dsh.settings.settings_file import SettingsService
from dsh.llm.llm_service import LLMService


def test_resolve_dsh_home():
    old_env = os.environ.get("DSH_HOME")
    try:
        os.environ["DSH_HOME"] = "D:\\custom_dsh_home"
        assert resolve_dsh_home() == os.path.abspath("D:\\custom_dsh_home")

        assert resolve_dsh_home("C:\\explicit_home") == os.path.abspath("C:\\explicit_home")

        del os.environ["DSH_HOME"]
        assert resolve_dsh_home() == os.path.abspath(os.path.join(os.path.expanduser("~"), ".dsh"))
    finally:
        if old_env is not None:
            os.environ["DSH_HOME"] = old_env
        else:
            os.environ.pop("DSH_HOME", None)


def test_parse_dotenv():
    content = """
    # Comment line
    FOO=bar
    export BAZ="hello world"
    QUOTED='single quoted'
    ESCAPED="line1\\nline2"
    EMPTY=
    """
    res = parse_dotenv(content)
    assert res["FOO"] == "bar"
    assert res["BAZ"] == "hello world"
    assert res["QUOTED"] == "single quoted"
    assert res["ESCAPED"] == "line1\nline2"
    assert res["EMPTY"] == ""


def test_security_tripwires():
    assert is_bootstrap_only("PATH") is True
    assert is_bootstrap_only("path") is True
    assert is_bootstrap_only("PYTHONSTARTUP") is True
    assert is_bootstrap_only("DSH_PERMISSION_MODE") is True
    assert is_bootstrap_only("DSH_HOME") is True
    assert is_bootstrap_only("HTTP_PROXY") is True
    assert is_bootstrap_only("NODE_OPTIONS") is True
    assert is_bootstrap_only("BASH_ENV") is True

    # Non-bootstrap variables
    assert is_bootstrap_only("MY_CUSTOM_VAR") is False
    assert is_bootstrap_only("ANOTHER_API_KEY") is False


def test_load_layered_env_rejection():
    with tempfile.TemporaryDirectory() as project_dir:
        # 1. Dangerous .env setting PATH should raise ValueError
        env_file = os.path.join(project_dir, ".env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("PATH=C:\\malicious\\bin\n")

        with pytest.raises(ValueError) as exc:
            load_layered_env(bin_name="dsh", cwd=project_dir)
        assert "only the launching environment may set" in str(exc.value)

        # 2. Dangerous .env setting DSH_HOME should raise ValueError
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("DSH_HOME=C:\\malicious_home\n")

        with pytest.raises(ValueError) as exc:
            load_layered_env(bin_name="dsh", cwd=project_dir)
        assert "only the launching environment may set" in str(exc.value)


def test_load_layered_env_success():
    with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as project_dir:
        # Create user .env in home
        with open(os.path.join(home_dir, ".env"), "w", encoding="utf-8") as f:
            f.write("SHARED_VAR=from_user\nUSER_ONLY=user_val\n")

        # Create project .env
        with open(os.path.join(project_dir, ".env"), "w", encoding="utf-8") as f:
            f.write("SHARED_VAR=from_project\nPROJECT_ONLY=proj_val\n")

        snapshot = load_layered_env(bin_name="dsh", cwd=project_dir, custom_home=home_dir)

        # Project wins over user home
        shared_entry = snapshot.get("SHARED_VAR")
        assert shared_entry is not None
        assert shared_entry.value == "from_project"
        assert shared_entry.source == "project-env"

        user_entry = snapshot.get("USER_ONLY")
        assert user_entry is not None
        assert user_entry.value == "user_val"
        assert user_entry.source == "user-env"


def test_credentials_precedence_and_shadowing(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        creds_file = os.path.join(tmpdir, ".credentials.yaml")
        ctx = Context()
        creds = CredentialsService(ctx=ctx, credentials_file=creds_file)

        # 1. Unshadowed write succeeds
        creds.set_credential("DEEPSEEK_API_KEY", "sk-file-key")
        assert creds.resolve("DEEPSEEK_API_KEY") == "sk-file-key"
        desc = creds.describe("DEEPSEEK_API_KEY")
        assert desc["source"] == "file"
        assert desc["writable"] is True

        # 2. Inherited process environment overrides file (Wins)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-launch-env-key")
        assert creds.resolve("DEEPSEEK_API_KEY") == "sk-launch-env-key"
        desc = creds.describe("DEEPSEEK_API_KEY")
        assert desc["source"] == "env"
        assert desc["writable"] is False

        # Setting shadowed credential throws ValueError
        with pytest.raises(ValueError) as exc:
            creds.set_credential("DEEPSEEK_API_KEY", "sk-new-key")
        assert "supplied read-only by the launching environment" in str(exc.value)


def test_full_llm_config_precedence(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = Context()

        # Mount launch environment
        launch_env = LaunchEnvironmentSnapshot([
            {"source": "process", "values": {}},
            {"source": "project-env", "values": {"DEEPSEEK_MODEL": "model-from-env-file"}},
        ])
        ctx.set_service("launch_environment", launch_env)

        # Mount settings
        settings_file = os.path.join(tmpdir, "settings.yaml")
        settings = SettingsService(ctx=ctx, settings_file=settings_file)

        llm = LLMService(ctx=ctx)

        # 1. Default fallback
        assert llm.resolve_base_url() == "https://api.deepseek.com"
        assert llm.resolve_model() == "model-from-env-file"

        # 2. Settings file overrides environment file
        settings.set_setting("llm", "base_url", "https://settings.endpoint.com")
        settings.set_setting("llm", "model", "deepseek-settings-model")
        assert llm.resolve_base_url() == "https://settings.endpoint.com"
        assert llm.resolve_model() == "deepseek-settings-model"

        # 3. Static / CLI override wins over settings
        llm_static = LLMService(ctx=ctx, base_url="https://cli.override.com", model="cli-model")
        assert llm_static.resolve_base_url() == "https://cli.override.com"
        assert llm_static.resolve_model() == "cli-model"


def test_configuration_chain_loading_order():
    """
    Verify 5-level configuration chain loading order:
    System Defaults -> Home Settings (~/.dsh/settings.yaml) -> Workspace Config -> Preset Overrides -> CLI/Env
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = Context()
        settings_file = os.path.join(tmpdir, "settings.yaml")
        settings = SettingsService(ctx=ctx, settings_file=settings_file)

        # Level 1: System Defaults
        val1 = resolve_layered_config(ctx, "llm", "model", system_default="deepseek-chat")
        assert val1 == "deepseek-chat"

        # Level 2: Home Settings (~/.dsh/settings.yaml) overrides System Defaults
        settings.set_setting("llm", "model", "home-setting-model")
        val2 = resolve_layered_config(ctx, "llm", "model", system_default="deepseek-chat")
        assert val2 == "home-setting-model"

        # Level 3: Workspace Config overrides Home Settings
        val3 = resolve_layered_config(ctx, "llm", "model", system_default="deepseek-chat", workspace_value="workspace-model")
        assert val3 == "workspace-model"

        # Level 4: Preset Overrides overrides Workspace Config
        val4 = resolve_layered_config(
            ctx,
            "llm",
            "model",
            system_default="deepseek-chat",
            workspace_value="workspace-model",
            preset_override="preset-model",
        )
        assert val4 == "preset-model"

        # Level 5: CLI / Env overrides Preset Overrides (Wins)
        val5 = resolve_layered_config(
            ctx,
            "llm",
            "model",
            system_default="deepseek-chat",
            workspace_value="workspace-model",
            preset_override="preset-model",
            cli_env_value="cli-model",
        )
        assert val5 == "cli-model"
