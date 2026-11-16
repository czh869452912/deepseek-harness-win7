import pytest

from dsh.boot.plugin_install_spec import parse_install_spec, pinned_git_origin, dependency_spec, classify_install_failure, InvalidInstallSpecError
from scripts.rc022_install_spec_probe import observe


@pytest.mark.asyncio
async def test_install_spec_boundaries_and_failure_diagnostic_precedence():
    rows = await observe()
    assert len(rows) > 180
    specs = {row['input']: row for row in rows if row['kind'] == 'spec'}
    assert specs['@scope/pkg@^1.2']['parsed']['value']['range'] == '^1.2'
    assert specs['file:relative']['parsed']['error']['reason'] == 'a local path must be absolute'
    assert specs['pkg@']['parsed']['error']['name'] == 'InvalidInstallSpecError'
    assert specs['https://[bad]/a/b']['parsed']['error']['name'] == 'TypeError'
    assert specs['git://HOST/a/b']['parsed']['value']['host'] == 'HOST'
    assert specs['https://Host:443/a/b']['parsed']['value']['host'] == 'host'
    commit = 'a'*40
    assert pinned_git_origin('git+https://user:secret@HOST/a/b.git#'+commit+'&path:/packages/foo/') == 'host/a/b#packages/foo'
    assert pinned_git_origin('github:a/b#'+commit+'&'+commit) is None
    assert dependency_spec('pkg','https://user:secret@host/a.tgz?query=kept','C:/profile') == 'https://host/a.tgz?query=kept'
    assert classify_install_failure(dict(log='ERR_PNPM_IGNORED_BUILDS ENOSPC',timedOut=True)) == 'timeout'
    assert classify_install_failure(dict(log='ENOSPC',cause=dict(code='ENOENT'))) == 'pnpm-missing'
    assert classify_install_failure(dict(log='unable to access: The requested URL returned error: 403')) == 'unknown'
    assert classify_install_failure(dict(log='\u4e2dENOSPC\u6587')) == 'disk-full'


@pytest.mark.parametrize('value', ['', 'pkg@', './relative', 'pkg with spaces'])
def test_rejections_preserve_trimmed_spec_and_structured_reason(value):
    with pytest.raises(InvalidInstallSpecError) as caught:
        parse_install_spec('\ufeff '+value+'\u00a0')
    assert caught.value.spec == value
    assert caught.value.message == 'plugin-manager: '+caught.value.reason+': '+value
