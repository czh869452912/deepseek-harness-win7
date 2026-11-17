"""Market API reads and clone fallback compared with original repositoryFiles."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows = []
    for host, url in [('github.com', 'https://github.com/o/r.git'), ('gitlab.example', 'http://gitlab.example:8443/g/s/p.git'), ('git.example', 'https://git.example/o/r.git')]:
        for public in [True, False, 'offline']:
            for status in [200, 404, 401, 403, 500]:
                for action in ['read', 'readme']:
                    rows.append(dict(repository=dict(host=host, project='g/s/p' if host == 'gitlab.example' else 'o/r', url=url),
                        public=public, status=status, action=action, commit='a'*40 if status == 200 else None,
                        path='guide/a b#中.md' if action == 'read' else 'packages/a'))
    return rows


async def observe():
    from dsh.boot.market_repository_files_022 import RepositoryFiles
    from dsh.core.abort import AbortController
    from dsh.util.plugin_detail import DetailFailure
    rows = []
    for case in cases():
        calls = []; signal = AbortController().signal
        async def public(url):
            calls.append(dict(kind='public', url=url))
            if case['public'] == 'offline': raise DetailFailure('network', 'offline')
            return case['public']
        async def read(url, ref, path, maximum, signal):
            calls.append(dict(kind='read', url=url, ref=ref, path=path, maximum=maximum)); return b'clone'
        async def readme(url, ref, path, maximum, signal):
            calls.append(dict(kind='readme', url=url, ref=ref, path=path, maximum=maximum)); return dict(path=path+'/README.md', bytes=b'# Clone')
        async def fetch(url, maximum, signal, options):
            calls.append(dict(kind='fetch', url=url, maximum=maximum))
            # A public missing README tries subsequent conventional filenames.
            status = 200 if case['status'] == 404 and case['action'] == 'readme' and '/Readme.md' in url else case['status']
            return dict(ok=True, bytes=b'# API') if status == 200 else dict(ok=False, status=status)
        options = dict(timeoutMs=1000, lifetime=signal, gitlabHosts=['gitlab.example'], cache=SimpleNamespace(isPublic=public, read=read, readme=readme))
        files = RepositoryFiles(case['repository'], case['commit'], options, fetch)
        try:
            value = await getattr(files, case['action'])(case['path'], 100, signal)
            if isinstance(value, bytes): value = list(value)
            elif value is not None: value = dict(value, bytes=list(value['bytes']))
            rows.append(dict(key=files.key, calls=calls, value=value))
        except Exception as error:
            rows.append(dict(key=files.key, calls=calls, error=dict(reason=getattr(error, 'reason', None), message=str(error))))
    return rows


def prepare(output):
    path = output/'cases.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_market_files.mts', scope='GitHub/GitLab API URL encoding and HEAD/pinned ref, success/401/403/404/500, public/private/unreachable accessibility, README naming/fallback; controlled shared HTTP fetch and clone-cache collaborators, no actual clone acceptance.',
        prepare=prepare, extra_inputs=[ROOT/'dsh/boot/market_repository_files_022.py', ROOT/'scripts/rc022_market_files_probe.py'])
