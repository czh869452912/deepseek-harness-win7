"""Format-bound rc.3 checkpoints and predecessor title-only listing hints."""
from dsh.cordis.plugin import Plugin
from dsh.core.session.json import walk_json_value, UNDEFINED
from dsh.core.session.types import SessionLogOffset
from dsh.session.projection_cache import SessionProjectionCache, _record
from dsh.storage.domain_spec import define_domain, domain_table


def checkpoint_record(value):
    result = _record(value)
    version = result['identity'].get('formatVersion')
    if 'formatVersion' in result['identity'] and (type(version) not in (int, float) or version < 0 or not version <= 9007199254740991 or int(version) != version):
        raise ValueError('invalid checkpoint format version')
    return result


PROJECTION_CACHE_SPEC = define_domain(dict(name='session_projcache', version=7, compatibleVersions=[3, 4, 5, 6],
    invalidRecords='backup-and-skip', layout='per-record', tables=dict(sessions=domain_table(checkpoint_record))))


def identity_of(header, inherited_event_count):
    field = header.get if isinstance(header, dict) else lambda key, default=None: getattr(header, key, default)
    cut = SessionLogOffset(inherited_event_count)
    if not field('isSeeded') and cut != 0:
        raise ValueError('unseeded projection-cache identity inherited event count must be 0')
    result = dict(formatVersion=field('version'), createdAt=field('createdAt'), isSeeded=field('isSeeded'), inheritedEventCount=cut)
    if field('cwd') is not None:
        result['cwd'] = field('cwd')
    return result


def lifecycle_matches(stored, expected):
    return (stored.get('createdAt') == expected['createdAt'] and stored.get('cwd') == expected.get('cwd') and
        stored.get('isSeeded', False) == expected['isSeeded'] and stored.get('inheritedEventCount', 0) == expected['inheritedEventCount'])


class CurrentSessionProjectionCache(SessionProjectionCache):
    def _rows(self, header, inherited_event_count):
        expected = identity_of(header, inherited_event_count)
        sid = header['id'] if isinstance(header, dict) else header.id
        record = self.table.get(sid)
        return (record['rows'] if record is not None and record['identity'].get('formatVersion') == expected['formatVersion'] and
            lifecycle_matches(record['identity'], expected) else {})

    def cachedPredecessorTitle(self, header, inherited_event_count):
        expected = identity_of(header, inherited_event_count)
        sid = header['id'] if isinstance(header, dict) else header.id
        record = self.table.get(sid)
        if record is None:
            return None
        stored = record['identity']
        if not lifecycle_matches(stored, expected) or ('formatVersion' in stored and stored['formatVersion'] >= expected['formatVersion']):
            return None
        values = self.ctx.get('sessionProjections').viewCheckpoint(record['rows'], ['title'])
        return dict(asOfSeq=-1, values=values) if values else None

    async def _put(self, header, inherited_event_count, rows):
        snapshot = walk_json_value(rows, detach=True, undefined_sentinel=UNDEFINED)
        if snapshot is UNDEFINED:
            raise TypeError('projection checkpoint is not losslessly JSON-serializable (a unit state violates the plain-JSON contract)')
        sid = header['id'] if isinstance(header, dict) else header.id
        await self.table.put(sid, dict(identity=identity_of(header, inherited_event_count), rows=snapshot))


class HeaderSessionProjectionCache(CurrentSessionProjectionCache):
    """Header-only views never seed a fold or claim an exact log cut."""
    def _header_record(self, header, predecessor=False):
        expected = identity_of(header, 0)
        sid = header['id'] if isinstance(header, dict) else header.id
        record = self.table.get(sid)
        if record is None:
            return None
        stored = record['identity']
        version = stored.get('formatVersion')
        matches = ((version is None or version < expected['formatVersion']) if predecessor
                   else version == expected['formatVersion'])
        if not matches or any(stored.get(key, default) != expected.get(key, default)
                              for key, default in (('createdAt', None), ('cwd', None), ('isSeeded', False))):
            return None
        return record

    def _view_record(self, record, keys=None):
        if record is None:
            return None
        values = self.ctx.get('sessionProjections').viewCheckpoint(record['rows'], keys)
        if not values:
            return None
        return dict(asOfSeq=min(record['rows'][key]['seq'] for key in values), values=values)

    def cached_snapshot(self, header, keys=None):
        return self._view_record(self._header_record(header), keys)

    cachedSnapshot = cached_snapshot

    def cachedPredecessorTitle(self, header):
        return self._view_record(self._header_record(header, predecessor=True), ['title'])


class CurrentSessionProjectionCachePlugin(Plugin):
    id = 'session-projection-cache'
    inject = ['storageDomain', 'sessionProjections', 'sessions']
    cache_class = CurrentSessionProjectionCache

    async def apply(self, ctx):
        for key in ('writeEveryEvents', 'writeIntervalMs'):
            if type(self.config.get(key)) is not int or self.config[key] < 1:
                raise ValueError('session-projection-cache requires positive ' + key)
        domain = await ctx.get('storageDomain').open(PROJECTION_CACHE_SPEC)
        cache = self.cache_class(ctx, domain.table('sessions'), self.config)
        ctx.set_service('sessionProjectionCache', cache)
        ctx.on('session/event', cache.event)
        ctx.on('session/created', lambda session: cache._schedule(cache.write(session)))
        ctx.on('session/disposed', lambda session: cache._schedule(cache.write(session)))
        async def close():
            await cache.close()
            await domain.close()
        ctx.effect(lambda: close)


class HeaderSessionProjectionCachePlugin(CurrentSessionProjectionCachePlugin):
    cache_class = HeaderSessionProjectionCache
