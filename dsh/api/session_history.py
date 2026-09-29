"""Cold-safe pages and gap-free live history over the original Remote contract."""
import asyncio

from dsh.api.settings import failure
from dsh.core.session.chunk_rows import pack_chunk_runs, is_chunk_row
from dsh.core.surface import is_append_surface_event
from dsh.session.session_query import SessionQueryError


def paginate(events, before=None, maximum=50, through=None):
    end = min(len(events) if through is None else through + 1,
              len(events) if before is None else before)
    count, cut = 0, 0
    for index in range(end - 1, -1, -1):
        event = events[index]
        if event['type'] not in ('user/message', 'assistant/message') or not is_append_surface_event(event):
            continue
        count += 1
        if count >= maximum:
            cut = min([event['seq']] + list(event.get('sourceEventSeqs', [])))
            break
    return events[cut:end], cut > 0


def page_records(events):
    return [dict(type='chunks', event=dict(type='chunkrow/' + row['type'], seq=row['seq0'], time=row['time0'], data=row['data']))
            if is_chunk_row(row) else dict(type='event', event=row) for row in pack_chunk_runs(events)]


def validate_request(request, page=False):
    for key, minimum in ([('throughSeq', -1), ('beforeSeq', 0), ('maxMessages', 1)] if page else [('maxMessages', 1)]):
        if key not in request and key != 'throughSeq':
            continue
        value = request.get(key)
        if type(value) is not int or value < minimum or value > 9007199254740991:
            raise failure('bad-request', '%s must be a safe integer greater than or equal to %s' % (key, minimum))


class SessionHistory:
    def __init__(self, ctx, promote):
        self.ctx, self.promote, self.followers = ctx, promote, set()
        ctx.effect(lambda: self.close)

    def close(self):
        for queue in self.followers:
            queue.put_nowait(None)
        self.followers.clear()

    async def source(self, address, signal, projections):
        ordinary = address['kind'] == 'session'
        sid = address['sessionId'] if ordinary else address['childSessionId']
        try:
            observed = await self.ctx.get('sessionQuery').observeSession(sid, dict(signal=signal, projectionMode='all' if projections or not ordinary else 'none'))
        except SessionQueryError as error:
            if error.code != 'SESSION_QUERY_SESSION_NOT_FOUND':
                raise
            raise self.not_found(address) from error
        try:
            header = observed.header
            if header.cwd is None:
                raise self.not_found(address)
            if ordinary:
                if header.origin == 'subagent':
                    raise failure('agent-busy', 'subagent Sessions require their durable parent address', {'reason': 'use subagent delivery for this child session'})
            else:
                if header.origin != 'subagent' or header.parentSession != address['parentSessionId']:
                    raise failure('subagent-unauthorized', 'subagent does not belong to the supplied parent', {'childSessionId': sid})
                values = (observed.projections or {}).get('values', {})
                identity = values.get('subagent')
                if identity is None or identity['seq'] < (header.seedLength or 0):
                    raise failure('subagent-catalog-diagnostic', 'subagent descriptor is unavailable',
                                  dict(parentSessionId=address['parentSessionId'], childSessionId=sid,
                                       reason='corrupt' if 'subagent' in values and identity is None else 'unsupported'))
                if identity['mode'] != address['mode']:
                    raise failure('subagent-unauthorized', 'subagent mode does not match the supplied address', {'childSessionId': sid})
            return observed
        except BaseException:
            observed.dispose()
            raise

    @staticmethod
    def not_found(address):
        if address['kind'] == 'session':
            return failure('session-not-found', 'session "%s" not found' % address['sessionId'], {'sessionId': address['sessionId']})
        return failure('subagent-not-found', 'subagent is unavailable', {key: address[key] for key in ('parentSessionId', 'childSessionId')})

    async def page(self, request, signal):
        validate_request(request, True)
        source = await self.source(request['address'], signal, False)
        try:
            signal.throw_if_aborted()
            if request['throughSeq'] > source.cursor:
                raise failure('bad-request', 'session page through seq %s is past cursor %s' % (request['throughSeq'], source.cursor))
            events, more = paginate(source.events, request.get('beforeSeq'), request.get('maxMessages', 50), request['throughSeq'])
            return dict(records=page_records(events), hasMore=more)
        finally:
            source.dispose()

    async def follow(self, request, signal):
        validate_request(request)
        signal.throw_if_aborted()
        address = request['address']
        sid = address['sessionId'] if address['kind'] == 'session' else address['childSessionId']
        queue, cursor = asyncio.Queue(), None
        self.followers.add(queue)
        def event(session, value):
            if session.id == sid:
                queue.put_nowait(value)
        def created(session):
            if session.id == sid:
                for value in session.events[session.firstLiveSeq if cursor is None else cursor + 1:]:
                    queue.put_nowait(value)
        remove_event = self.ctx.on('session/event', event, global_listener=True)
        remove_created = self.ctx.on('session/created', created, global_listener=True)
        remove_abort = signal.add_listener('abort', lambda *_: queue.put_nowait(None))
        source = None
        try:
            source = await self.source(address, signal, True)
            signal.throw_if_aborted()
            cursor = source.cursor
            events, more = paginate(source.events, maximum=request.get('maxMessages', 50))
            yield dict(type='snapshot', header=source.header.to_dict(), cursor=cursor,
                       records=page_records(events), hasMore=more,
                       projections=source.projections or dict(asOfSeq=cursor, values={}))
            if address['kind'] == 'session' and source.source == 'prepared':
                self.promote(source.retain())
            next_seq = cursor + 1
            while not signal.aborted:
                item = await queue.get()
                if item is None:
                    return
                if item['seq'] < next_seq:
                    continue
                if item['seq'] != next_seq:
                    raise failure('internal', 'session event stream skipped seq %s' % next_seq)
                next_seq += 1
                yield dict(type='event', event=item)
        finally:
            if source is not None:
                source.dispose()
            remove_event()
            remove_created()
            remove_abort()
            self.followers.discard(queue)
