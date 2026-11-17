"""Anonymous repository file APIs with the original clone fallback boundary."""
from urllib.parse import quote, urlsplit

from dsh.util.plugin_detail import DetailFailure, README_NAMES, encode_path, readme_by_name
from dsh.util.plugin_detail_http import fetch_body


def component(value):
    return quote(value, safe="-_.!~*'()", encoding='utf-8')


class RepositoryFiles:
    def __init__(self, repository, commit, options, fetch=None):
        self.repository, self.commit, self.options = repository, commit, options
        self.fetch = fetch or fetch_body
        self.api = 'github' if repository['host'] == 'github.com' else 'gitlab' if repository['host'] in options['gitlabHosts'] else None
        self.ref = 'HEAD' if commit is None else commit
        self.key = 'git:'+repository['url']+'#'+self.ref

    def api_url(self, path):
        if self.api == 'github':
            return 'https://raw.githubusercontent.com/'+self.repository['project']+'/'+component(self.ref)+'/'+encode_path(path)
        parsed = urlsplit(self.repository['url'])
        return parsed.scheme+'://'+parsed.netloc+'/api/v4/projects/'+component(self.repository['project'])+'/repository/files/'+component(path)+'/raw?ref='+component(self.ref)

    async def from_api(self, path, max_bytes, signal):
        body = await self.fetch(self.api_url(path), max_bytes, signal, self.options)
        if body['ok']:
            return body['bytes']
        if body['status'] not in (404, 401, 403):
            raise DetailFailure('network', self.repository['url']+': '+path+' answered HTTP '+str(body['status']))
        return None

    async def read(self, path, max_bytes, signal):
        cache = self.options['cache']
        if self.api is not None:
            data = await self.from_api(path, max_bytes, signal)
            if data is not None or await cache.isPublic(self.repository['url']):
                return data
        return await cache.read(self.repository['url'], self.commit, path, max_bytes, signal)

    async def readme(self, directory, max_bytes, signal):
        cache = self.options['cache']
        if self.api is not None:
            found = await readme_by_name(self.from_api, directory, max_bytes, signal, README_NAMES[:1])
            if found is not None:
                return found
            if await cache.isPublic(self.repository['url']):
                return await readme_by_name(self.from_api, directory, max_bytes, signal, README_NAMES[1:])
        return await cache.readme(self.repository['url'], self.commit, directory, max_bytes, signal)
