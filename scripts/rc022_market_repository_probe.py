"""Pure original repository identity and manifest-directory projection."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    urls = ['github:o/r', 'o/r', 'gitlab:g/s/p', 'bitbucket:o/r', 'gist:abc', 'gist:o/abc',
        'https://github.com/o/r/tree/main/pkg', 'https://github.com/o/r/issues/1', 'git@github.com:o/r.git',
        'ssh://git@github.com/o/r.git', 'git+ssh://git@github.com/o/r.git', 'https://github.com/o/r.git#semver:^1',
        'git+https://gitlab.com/g/s/p.git#main', 'https://gitlab.com/g/p/-/tree/main',
        'https://git.corp.example/g/p/-/tree/main', 'https://git.example/team/repo', 'https://git.example/one',
        'https://user:pw@git.example/a/b', 'https://u:p@github.com/o/r', 'http://intranet/a/b/',
        'https://git.example:8443/a/b.git', 'git+https://git.example/a/b.git', 'ssh://git@git.example/a/b',
        'file:///a/b', 'ftp://git.example/a/b', 'not a repository', '', 'https://例子.测试/团队/仓库',
        'https://github.com/O/R.GIT', 'https://git.example/a//b', 'https://git.example/a/b?q=1#main',
        'https://git.example/a/%2e%2e/b/c', 'https://[::1]:8443/a/b', 'https://github.com/o/r/']
    directories = ['', '.', './', './packages/a/', 'a/../b', 'a/../../b', '../x', '..', '/abs', '//server/share',
        'a//b/', 'a/./b', 'a\\b\\..\\c', '\\abs', 'C:\\foo', 'C:/foo', 'a/../', 'a/.../b', '\0x', '\ud800', 7, None]
    rows = [dict(kind='repository', value=url) for url in urls]
    for url in urls:
        rows.append(dict(kind='manifest-repository', value=url))
        for directory in directories:
            rows.append(dict(kind='manifest-repository', value=dict(type='git', url=url, directory=directory)))
    rows += [dict(kind='manifest-repository', value=value) for value in [None, 7, [], {}, {'url': 7}, {'directory': 'x'}]]
    return rows


async def observe():
    from dsh.boot.market_index_022 import observe_market_operations
    return observe_market_operations(cases())


def prepare(output):
    path = output/'operations.json'; path.write_text(json.dumps(cases(), ensure_ascii=True), encoding='utf-8'); return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_repository.mts', scope='Unchanged Source repositoryOf/manifestRepository/normalizedDirectory with pinned hosted-git-info; URL/shorthand/Git/host cases crossed with POSIX directory normalization/admission including Windows drive/backslash/surrogate inputs. Pure identities only; no network or Git clone.',
        prepare=prepare, extra_inputs=[ROOT/'dsh/boot/market_repository_022.py', ROOT/'dsh/boot/market-index/manifest.json', ROOT/'scripts/rc022_market_repository_probe.py', ROOT/'scripts/native/market-index/posix.ts', ROOT/'scripts/native/market-index/url.ts'])
