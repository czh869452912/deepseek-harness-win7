"""
Test for G12 D2: Fail-loud on unknown profile bundles in dsh/cordis/profile.py.
Verifies RuntimeError is raised without NameError, matching dsh/boot/profile.py:733-736 verbatim.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import json
import os
import tempfile
import pytest

from dsh.cordis.profile import compose_profile, BUILTIN_PROFILES, Profile


def test_compose_profile_unknown_bundle_raises_runtime_error_not_name_error():
    """G12 D2 pin test: Unknown bundle in profile raises RuntimeError with JSON-quoted bundle name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock custom profile that specifies an unknown bundle
        prof_dir = os.path.join(tmpdir, "profiles", "custom-broken")
        os.makedirs(prof_dir, exist_ok=True)
        with open(os.path.join(prof_dir, "cordis.patch.yml"), "w", encoding="utf-8") as f:
            f.write("[]\n")

        # Temporarily register custom broken profile in BUILTIN_PROFILES
        BUILTIN_PROFILES["custom-broken"] = {
            "bundles": ["@deepseek-ai/dsh-unknown-nonexistent-bundle"],
            "patches": [],
        }
        try:
            with pytest.raises(RuntimeError) as exc_info:
                compose_profile("custom-broken", dsh_home=tmpdir)

            err_msg = str(exc_info.value)
            assert "cannot resolve profile bundle" in err_msg
            assert json.dumps("@deepseek-ai/dsh-unknown-nonexistent-bundle") in err_msg
            assert "run 'dsh plugin --profile custom-broken install'" in err_msg
            assert "if its dependency is not installed" in err_msg
        finally:
            BUILTIN_PROFILES.pop("custom-broken", None)
