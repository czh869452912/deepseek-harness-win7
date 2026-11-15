"""The compatibility facade reports canonical skipped bundle admission."""
import json
from dsh.cordis.profile import compose_profile
from dsh.boot.profile import init_profile


def test_compose_profile_reports_unknown_bundle_without_a_builtin_fallback(tmp_path):
    package = '@deepseek-ai/dsh-unknown-nonexistent-bundle'
    directory = tmp_path/'profiles/custom-broken'
    init_profile(str(directory), [package])
    composed = compose_profile('custom-broken', dsh_home=str(tmp_path))
    assert composed.bundle_patches == []
    assert len(composed.profile.skippedBundles) == 1
    skipped = composed.profile.skippedBundles[0]
    assert skipped['packageName'] == package
    assert 'cannot resolve profile bundle '+json.dumps(package) in skipped['reason']
