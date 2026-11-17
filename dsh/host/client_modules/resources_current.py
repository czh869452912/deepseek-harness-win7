"""Current immutable client resources, materialized independently on first GET."""
import asyncio
import inspect
from urllib.parse import urljoin, urlsplit

from dsh.cordis.json_text import stringify_json
from dsh.host.client_modules.registry import (
    combo_source, combo_url, framed_hash, identity_section_map,
)


class LazyBody:
    """Share one producer; retain success and permit retry after rejection.

    A cancelled Python carrier leaves the shared producer running, like a
    cancelled Fetch consumer leaves the Source Promise's settlement intact.
    """
    def __init__(self, produce):
        self.produce = produce
        self.task = None

    async def __call__(self):
        if self.task is None:
            async def run():
                value = self.produce()
                return await value if inspect.isawaitable(value) else value
            task = asyncio.create_task(run())
            self.task = task
            def settled(result):
                if result.cancelled() or result.exception() is not None:
                    if self.task is result:
                        self.task = None
            task.add_done_callback(settled)
        return await asyncio.shield(self.task)


def prepared(resource):
    source, fallback = combo_source(resource)
    # The historical helper's default is always client.js. Split resources
    # instead retain the requested file's generated-source name.
    if fallback == '/plugins/%s/client.js' % resource['id']:
        from dsh.host.client_modules.registry import SOURCE_URL_TRAILER
        if SOURCE_URL_TRAILER.search(resource['bundle'].decode('utf-8', errors='replace')) is None:
            fallback = '/plugins/%s/%s' % (resource['id'], resource['file_name'])
    return source, fallback


def script_body(resources, map_reference):
    source = ''.join(prepared(resource)[0] + ';\n' for resource in resources)
    return (source + '//# sourceMappingURL=' + map_reference + '\n').encode('utf-8')


def section_map(resource, original):
    root = original.get('sourceRoot')
    root = root if isinstance(root, str) else ''
    base = 'http://dsh.invalid/plugins/%s/client.js.map' % resource['id']
    sources = []
    for source in original['sources']:
        separator = '/' if root and not root.endswith('/') and not source.startswith('/') else ''
        resolved = urljoin(base, root + separator + source)
        parts = urlsplit(resolved)
        # Access hostname as well: malformed IPv6 authored URLs reject like URL.
        hostname = parts.hostname
        if parts.scheme == 'http' and parts.netloc == 'dsh.invalid':
            resolved = parts.path + ('?' + parts.query if parts.query else '') + ('#' + parts.fragment if parts.fragment else '')
        sources.append(resolved)
    section = dict(original, sources=sources)
    section.pop('sourceRoot', None)
    return section


def source_map_body(resources, source_map_of, file_name='client.js'):
    sections = []
    line = 0
    for resource in resources:
        source, fallback = prepared(resource)
        original = source_map_of(resource['client_path'])
        section = identity_section_map(source, fallback)
        if original is not None:
            try:
                section = section_map(resource, original)
            except (ValueError, TypeError):
                pass
        sections.append(dict(offset=dict(line=line, column=0), map=section))
        line += (source + ';\n').count('\n')
    return (stringify_json(dict(version=3, file=file_name, sections=sections)) + '\n').encode('utf-8')


def build_combo(records, source_map_of, revision=None):
    # Snapshot only fields read by the response: later HMR must not change an
    # already advertised generation whose body has not yet been requested.
    resources = [dict(id=record['id'], rev=record['entry']['rev'],
        client_path=record['meta']['client_path'], file_name='client.js', bundle=record['bundle']) for record in records]
    revision = revision if revision is not None else framed_hash('combo', [
        part.encode('utf-8') for resource in resources for part in (resource['id'], resource['rev'])])
    entries = [resource['id'] for resource in resources]
    url, map_url = combo_url(entries, revision), combo_url(entries, revision, True)
    return dict(url=url, sourceMapUrl=map_url, rev=revision, entries=entries,
        scriptBody=LazyBody(lambda: script_body(resources, map_url[len('/plugins/'): ])),
        sourceMapBody=LazyBody(lambda: source_map_body(resources, source_map_of)))
