"""
1:1 parity suite for module-HMR ownership across the real shipped profile
bundle layers.

Matching reference/apps/cli/tests/profile-hmr.spec.ts.
"""

import os

import pytest

from dsh.boot.app_boot import load_overlay_patches
from dsh.boot.profile import compose_entries

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BIN_NAME = "profile-hmr test"


def bundle(name):
    """Load one shipped bundle patch through the same parser as profile boot."""
    return load_overlay_patches(BIN_NAME, os.path.join(REPOSITORY_ROOT, "packages", "bundle", name, "cordis.patch.yml"))


def hmr(layers):
    """Resolve the effective HMR row after the supplied layers."""
    row = next((entry for entry in compose_entries(layers) if entry.get("id") == "hmr"), None)
    if row is None:
        raise AssertionError("the base bundle must insert the hmr row")
    return row


def test_web_inherits_the_profile_owned_configuration_watch_row():
    row = hmr([bundle('base'), bundle('web-app')])
    assert row['name'] == '@deepseek-ai/dsh-hmr'
    assert row['disabled'] == {'__jsExpr': "!ctx.get('profileContext')"}
    assert row['config'] == {'root': []}


@pytest.mark.parametrize('mode', ['headless', 'sdk-app', 'acp-app'])
def test_noninteractive_modes_disable_the_yaml_owned_row(mode):
    row = hmr([bundle('base'), bundle(mode)])
    assert row['disabled'] is True
    assert row['config'] == {'root': []}


def test_requires_an_explicit_later_layer_to_enable_source_module_reload():
    row = hmr([bundle("base"), [{"id": "hmr", "disabled": False}]])
    assert row["disabled"] is False
    assert row["config"] == {"root": []}


def test_keeps_the_standalone_sdk_minimal_tree_free_of_module_hmr():
    assert next((entry for entry in compose_entries([bundle("sdk-minimal")]) if entry.get("id") == "hmr"), None) is None
