import os
import sys
from apps.cli.main import parse_args


def test_parse_args_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dsh.py"])
    args = parse_args()
    assert args.mode == "standard"
    assert args.profile is None
    assert args.port == 8080
    assert args.host == "127.0.0.1"
    assert args.dump_config is False
    assert args.web is False


def test_parse_args_profile_and_web_flags(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "dsh.py",
        "--profile", "web",
        "--port", "9090",
        "--host", "0.0.0.0",
        "--no-open",
        "--dump-config",
        "--patch", "custom.patch.yml",
    ])
    args = parse_args()
    assert args.profile == "web"
    assert args.port == 9090
    assert args.host == "0.0.0.0"
    assert args.no_open is True
    assert args.dump_config is True
    assert args.patch == "custom.patch.yml"


def test_parse_args_mode_aliases(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["dsh.py", "-m", "minimal"])
    args = parse_args()
    assert args.mode == "minimal"

    monkeypatch.setattr(sys, "argv", ["dsh.py", "-m", "极简模式"])
    args2 = parse_args()
    assert args2.mode == "极简模式"
