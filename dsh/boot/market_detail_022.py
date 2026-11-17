"""Market detail document/image ownership over shared package file readers.

Repository resolution and repository files are injected provider contracts here;
network and Git cache qualification belong to those providers.
"""
import asyncio
import hashlib
import json
import time

from dsh.util.plugin_detail import (DetailFailure, detail_image, join_path,
                                    markdown_of, read_package_document)

LASTING_FAILURES = {'too-large', 'denied', 'invalid'}


def utf8(text):
    return text.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='replace').encode('utf-8')


class MarketDetailReader:
    def __init__(self, limits, repositories, repository_files, manifest_repository, clock=None):
        self.limits, self.repositories = limits, repositories
        self.repository_files, self.manifest_repository = repository_files, manifest_repository
        self.clock = clock or (lambda: int(time.time()*1000))
        self.results, self.pending, self.documents = {}, {}, {}

    async def read(self, location, languages, refresh=False):
        repository = location.get('repository')
        repository_key = repository if isinstance(repository, str) else '' if repository is None else repository['url']+':'+repository['directory']
        files = location.get('files')
        key = json.dumps(['' if files is None else files.key, location['dir'], repository_key, languages],
                         ensure_ascii=True, separators=(',', ':'))
        cached = self.results.get(key)
        if not refresh and cached is not None and cached['expiresAt'] > self.clock():
            if 'failure' in cached:
                raise cached['failure']
            value = cached['value']
            if value['status'] == 'found':
                self.use(value['document'])
            return value
        if key not in self.pending:
            async def resolve():
                try:
                    value = await self.resolve(location, languages, self.repositories['lifetime'])
                    self.remember(key, dict(value=value, expiresAt=self.clock()+self.limits['ttlMs']))
                    return value
                except DetailFailure as error:
                    if error.reason in LASTING_FAILURES:
                        self.remember(key, dict(failure=error, expiresAt=self.clock()+self.limits['ttlMs']))
                    raise
                finally:
                    self.pending.pop(key, None)
            task = asyncio.create_task(resolve())
            task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            self.pending[key] = task
        return await asyncio.shield(self.pending[key])

    async def image(self, identity, authored):
        document = self.use(identity)
        image = None if document is None else detail_image(document['path'], authored)
        if document is None or image is None:
            return None
        data = await document['files'].read(image['path'], self.limits['maxImageBytes'], self.repositories['lifetime'])
        return None if data is None else dict(bytes=data, mediaType=image['mediaType'])

    def use(self, identity):
        now = self.clock()
        for known, document in list(self.documents.items()):
            if now-document['usedAt'] > self.limits['ttlMs']:
                del self.documents[known]
        document = self.documents.get(identity)
        if document is not None:
            document['usedAt'] = now
        return document

    def remember(self, key, read):
        now = self.clock()
        for known, cached in list(self.results.items()):
            if cached['expiresAt'] <= now:
                del self.results[known]
        self.results[key] = read

    async def resolve(self, location, languages, signal):
        files, directory = location.get('files'), location['dir']
        repository = None if location.get('repository') == 'manifest' else location.get('repository')
        if files is not None:
            document = await read_package_document(files, directory, languages, self.limits['maxDocumentBytes'], signal)
            if document is not None:
                return self.found(document['origin'], files, document['path'], document['markdown'])
            if location.get('repository') == 'manifest':
                repository = await self.manifest_repository_of(files, directory, signal)
        if repository is None:
            return dict(status='none')
        source = self.repository_files(repository, None, self.repositories)
        readme = await source.readme(repository['directory'], self.limits['maxDocumentBytes'], signal)
        return dict(status='none') if readme is None else self.found('repository', source, readme['path'], markdown_of(readme['bytes']))

    async def manifest_repository_of(self, files, directory, signal):
        data = await files.read(join_path(directory, 'package.json'), self.limits['maxDocumentBytes'], signal)
        if data is None:
            return None
        try:
            def invalid(value): raise ValueError('Invalid JSON constant: '+value)
            value = json.loads(data.decode('utf-8-sig', errors='replace'), parse_constant=invalid)
            return self.manifest_repository(value.get('repository') if isinstance(value, dict) else None)
        except Exception:
            return None

    def found(self, origin, files, path, markdown):
        identity = hashlib.sha256(utf8(files.key+'\0'+path)).hexdigest()[:32]
        self.documents[identity] = dict(files=files, path=path, usedAt=self.clock())
        self.use(identity)
        return dict(status='found', origin=origin, markdown=markdown, document=identity)
