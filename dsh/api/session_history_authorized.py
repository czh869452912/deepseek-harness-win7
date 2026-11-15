"""Passive v4 history snapshots, exact projection reads and borrowed leases."""
import inspect
from dsh.core.session.types import SessionSeq, SessionLogOffset

from dsh.api.session_history_current import (
    safe_integer, negative_zero, address_id, not_found, page_records,
    validate_address as legacy_validate_address,
)
from dsh.typert.remote import RemoteError, remote_error_of
from dsh.cordis.errors import ThrownValueError
from dsh.api.session_listeners import EventListener, ProjectionListener


def failure_code(error):
    if isinstance(error, ThrownValueError):
        return error.value.get('code') if isinstance(error.value, dict) else None
    return getattr(error, 'code', None)


def resolve_history_request(request):
    if 'throughSeq' in request:
        value = request['throughSeq']
        if not safe_integer(value) or value < -1 or negative_zero(value):
            raise RemoteError('gateway/bad-request', 'throughSeq must be an integer greater than or equal to -1', {})
    if 'beforeSeq' in request:
        value = request['beforeSeq']
        if not safe_integer(value) or value < 0 or negative_zero(value):
            raise RemoteError('gateway/bad-request', 'beforeSeq must be a non-negative safe integer', {})
    maximum = request.get('maxMessages', 50)
    if not safe_integer(maximum) or maximum <= 0:
        raise RemoteError('gateway/bad-request', 'maxMessages must be a positive safe integer', {})
    window = request.get('turnWindow')
    if window is not None:
        if not safe_integer(window.get('minMessages')) or not 0 < window['minMessages'] <= maximum:
            raise RemoteError('gateway/bad-request', 'turnWindow.minMessages must be a positive safe integer no greater than maxMessages', {})
        if not safe_integer(window.get('minTurns')) or window['minTurns'] <= 0:
            raise RemoteError('gateway/bad-request', 'turnWindow.minTurns must be a positive safe integer', {})
    return dict(request, maxMessages=maximum)


def paginate(events, before, maximum, through, window=None):
    end = int(min(through + 1, before if before is not None else through + 1))
    count, turns, cut = 0, 0, 0
    for index in range(end - 1, -1, -1):
        event = events[index]
        if window is not None and event['type'] == 'turn/start':
            turns += 1
            if count >= window['minMessages'] and turns >= window['minTurns']:
                cut = index
                break
        if event['type'] not in ('user/message', 'assistant/message') or event.get('surfaceOp') != 'append':
            continue
        count += 1
        if count >= maximum:
            cut = int(min([event['seq']] + list(event.get('sourceEventSeqs', []))))
            break
    return events[cut:end], cut > 0


def validate_observation_address(address, observation):
    if observation.header.cwd is None:
        raise not_found(address)
    # Unknown mode deliberately accepts the durable descriptor's actual mode.
    actual = address
    if address['kind'] == 'subagent' and address['mode'] == 'unknown':
        identity = ((observation.projections or {}).get('values') or {}).get('subagent')
        if identity is not None:
            actual = dict(address, mode=identity['mode'])
    legacy_validate_address(actual, observation.header, observation.inheritedEventCount, observation.projections)


def history(observation, request):
    requested = request.get('throughSeq', observation.cursor)
    cursor = -1 if requested == -1 else int(SessionSeq(requested))
    if cursor > observation.cursor:
        raise RemoteError('gateway/bad-request', 'session history cut {} exceeds {}'.format(cursor, observation.cursor), {})
    before = SessionLogOffset(request['beforeSeq']) if 'beforeSeq' in request else None
    events, more = paginate(observation.events, before, request['maxMessages'], cursor, request.get('turnWindow'))
    return dict(cursor=cursor, records=page_records(events), hasMore=more)


def projections(observation):
    if observation.projections is None:
        raise RemoteError('session/projections-unavailable', 'Session projections are unavailable', {})
    return dict(asOfSeq=observation.projections['asOfSeq'], values=observation.projections['values'])


class SessionHistoryReads:
    """Read side of the History Controller; stream providers are composed separately."""
    def __init__(self, ctx):
        self.ctx = ctx

    async def observeEvent(self, request, signal):
        listener = EventListener(self.ctx, address_id(request['address']), signal)
        source = listener.events()
        try:
            yield dict(type='ready')
            async for item in source:
                yield item
        finally:
            await source.aclose()
            listener.dispose()

    async def observeProjections(self, request, signal):
        listener = ProjectionListener(self.ctx, request['sessionId'], signal)
        source = listener.changes()
        try:
            yield dict(type='ready')
            async for item in source:
                yield item
        finally:
            await source.aclose()
            listener.dispose()

    async def usingObservation(self, request, signal, callback=None):
        sid = request['sessionId']
        try:
            observation = await self.ctx.get('sessionQuery').observeSession(sid, dict(signal=signal,
                projectionMode='all' if request['projection'] else 'none'))
        except Exception as error:
            code = failure_code(error)
            if code == 'SESSION_QUERY_SESSION_NOT_FOUND':
                raise RemoteError('session/not-found', 'session "{}" not found'.format(sid), dict(sessionId=sid)) from None
            if code == 'SESSION_QUERY_ABORTED':
                raise RemoteError('gateway/cancelled', 'Session read was cancelled' if isinstance(error, ThrownValueError) else str(error), {}, cause=error) from None
            raise
        try:
            signal.throwIfAborted()
        except BaseException:
            observation.dispose()
            raise
        if callback is None:
            return observation
        try:
            result = callback(observation)
            return await result if inspect.isawaitable(result) else result
        finally:
            observation.dispose()

    async def events(self, request, signal):
        spec = resolve_history_request(request)
        address = request['address']
        def read(observation):
            validate_observation_address(address, observation)
            return history(observation, spec)
        try:
            return await self.usingObservation(dict(sessionId=address_id(address), projection=address['kind']=='subagent'), signal, read)
        except Exception as error:
            remote = remote_error_of(error)
            if remote is not None and remote['code'] == 'session/not-found':
                raise not_found(address) from None
            raise

    async def projections(self, request, signal):
        sid = request['sessionId']
        if not sid:
            raise RemoteError('gateway/bad-request', 'sessionId must not be empty', {})
        try:
            signal.throwIfAborted()
            live = self.ctx.get('sessions').get(sid)
            if live is not None:
                return dict(kind='sequenced', **self.ctx.get('sessionProjections').snapshot(live))
            persistence = self.ctx.get('sessionPersistence')
            stored = await persistence.stat(sid, dict(signal=signal)) if persistence is not None else None
            signal.throwIfAborted()
            if stored is not None and stored.get('formatStatus') == 'migration-required':
                cache = self.ctx.get('sessionProjectionCache')
                cached = cache.cachedSnapshot(stored['header']) if cache is not None else None
                return dict(kind='migration-required', values=dict(cached['values']) if cached is not None else {})
            return await self.usingObservation(dict(sessionId=sid, projection=True), signal,
                lambda observation:dict(kind='sequenced', **projections(observation)))
        except Exception as error:
            code = failure_code(error)
            if code in ('SESSION_QUERY_SESSION_NOT_FOUND', 'session/not-found'):
                return None
            if signal.aborted or code == 'SESSION_QUERY_ABORTED':
                raise RemoteError('gateway/cancelled', 'Session projection read was cancelled', {}, cause=error) from None
            if remote_error_of(error) is not None:
                raise
            raise RemoteError('gateway/internal', 'Session projection read failed', {}, cause=error) from None

    async def assistantOutput(self, session_id, after_seq, through_seq, maximum, signal):
        def read(observation):
            if through_seq > observation.cursor:
                raise RemoteError('gateway/internal', 'Session history no longer covers the wait cursor', {})
            records = []
            for index in range(through_seq, after_seq, -1):
                event = observation.events[index]
                if event['type'] != 'assistant/message' or event.get('surfaceOp') != 'append':
                    continue
                if len(records) == maximum:
                    return dict(records=records, truncated=True)
                records.append(dict(type='event', event=event))
            return dict(records=records, truncated=False)
        return await self.usingObservation(dict(sessionId=session_id, projection=False), signal, read)
