import pytest
from apps.cli.args import parse_dsh_args


def test_launcher_owns_only_prefix_flags():
    invocation = parse_dsh_args(["--profile", "web", "--patch", "custom.yml", "--port", "9090", "--dump-config"])
    assert invocation == {"mode": "profile", "profile": "web", "patches": ["custom.yml"], "args": ["--port", "9090", "--dump-config"]}


def test_web_alias_uses_same_profile():
    assert parse_dsh_args(["web", "--port", "9090"]) == parse_dsh_args(["--profile", "web", "--port", "9090"])


def test_dump_cannot_silently_ignore_app_flags():
    with pytest.raises(SystemExit):
        parse_dsh_args(["--profile", "web", "--dump-config", "--port", "9090"])
