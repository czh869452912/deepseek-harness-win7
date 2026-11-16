import pytest
from dsh.boot.plugin_registry_policy import (registry_plan,UNSPECIFIED,normalize_registry,attribute_failure,newer_versions,version_facts)


@pytest.mark.parametrize('requested,expected', [(UNSPECIFIED,[None]),(None,[None]),('https://mirror.example',['https://mirror.example/']),('https://CORP.example',['https://corp.example/'])])
def test_private_registry_never_participates_in_public_fallback(requested,expected):
    assert registry_plan(requested,dict(registry=None,fallbackRegistries=['https://mirror.example/'],resolved='https://corp.example/')) == expected


def test_registry_default_deduplication_and_explicit_public_retry():
    configured=dict(registry=None,fallbackRegistries=['https://mirror.example/','https://other.example/'],resolved='https://mirror.example/')
    assert registry_plan(UNSPECIFIED,configured) == [None,'https://other.example/']
    assert registry_plan('https://mirror.example',configured) == ['https://mirror.example/','https://other.example/']
    assert normalize_registry('https://HOST:443/a/../registry?q=x#f') == 'https://host/registry/?q=x#f'


def test_only_error_lines_attribute_remote_spec_host_failures():
    spec=dict(kind='git',host='github.com')
    assert attribute_failure('network','WARN github.com\nERR_PNPM_FETCH_FAIL registry.example',spec) == 'registry'
    assert attribute_failure('network','fatal: GITHUB.COM',spec) == 'spec-host'
    assert attribute_failure('permission','fatal: GITHUB.COM',spec) == 'other'


def test_version_candidates_keep_publication_identity_and_manifest_nulls():
    assert newer_versions(dict(versions=['v2.0.0','2.0.0-beta.10','2.0.0-beta.2','invalid'],time={'v2.0.0':'date'},**{'dist-tags':{'latest':'v2.0.0'}}),'1.0.0') == [
        dict(version='v2.0.0',publishedAt='date',tags=['latest'],prerelease=False),
        dict(version='2.0.0-beta.10',tags=[],prerelease=True),dict(version='2.0.0-beta.2',tags=[],prerelease=True)]
    assert version_facts(dict(engines=None,peerDependencies=False,dsh=dict(bundle={})), 'x','1.0.0') == dict(manifest=dict(name='x',version='1.0.0',engines=None,peerDependencies=False),bundle=True)
    with pytest.raises(ValueError):newer_versions(None,'1.0.0')
