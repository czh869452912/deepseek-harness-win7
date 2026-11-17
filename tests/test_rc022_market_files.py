import pytest

from dsh.boot.market_repository_files_022 import RepositoryFiles
from scripts.rc022_market_files_probe import observe


@pytest.mark.asyncio
async def test_api_and_clone_selection_corpus():
    rows = await observe()
    assert len(rows) == 90
    assert rows[0]['value'] == [35, 32, 65, 80, 73]
    assert rows[0]['calls'][0]['url'].endswith('/'+'a'*40+'/guide/a%20b%23%E4%B8%AD.md')
    assert rows[-1]['value']['bytes'] == list(b'# Clone')
    assert all(len(row['calls']) == 1 for row in rows[60:])


def test_gitlab_origin_retains_http_and_port_and_encodes_entire_project():
    files = RepositoryFiles(dict(host='gitlab.example', project='g/s/p', url='http://gitlab.example:8443/g/s/p.git'),
        None, dict(gitlabHosts=['gitlab.example']))
    assert files.api_url('guide/a b.md') == 'http://gitlab.example:8443/api/v4/projects/g%2Fs%2Fp/repository/files/guide%2Fa%20b.md/raw?ref=HEAD'


def test_github_is_always_api_host_and_gitlab_requires_configuration():
    assert RepositoryFiles(dict(host='github.com', project='o/r', url='https://github.com/o/r.git'), None, dict(gitlabHosts=[])).api == 'github'
    assert RepositoryFiles(dict(host='gitlab.com', project='o/r', url='https://gitlab.com/o/r.git'), None, dict(gitlabHosts=[])).api is None
