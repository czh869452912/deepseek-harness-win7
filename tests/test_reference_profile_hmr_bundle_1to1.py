import pytest
from dsh.cordis.profile import compose_profile, BUILTIN_BUNDLES, BUILTIN_PROFILES
from dsh.cordis.loader import apply_entry_patches


@pytest.mark.parametrize('mode', ['web', 'headless', 'sdk', 'acp'])
def test_profile_module_hmr_policy_inheritance(mode):
    # Verify profile bundle compose matches reference profile-hmr.spec.ts
    composed = compose_profile(mode)
    assert composed is not None
    assert composed.profile is not None
    assert composed.profile.name == mode


def test_custom_patch_hmr_override():
    base_entries = [{'id': 'hmr', 'disabled': True, 'config': {'root': ['.']}}]
    custom_patch = [{'id': 'hmr', 'disabled': False}]
    composed = apply_entry_patches(base_entries, custom_patch)
    hmr_row = next((e for e in composed if e.get('id') == 'hmr'), None)
    assert hmr_row is not None
    assert hmr_row['disabled'] is False
    assert hmr_row['config'] == {'root': ['.']}
