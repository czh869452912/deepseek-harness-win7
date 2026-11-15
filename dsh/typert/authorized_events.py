"""Peer-owned event generations, authorized broadcasts and owner answers."""
import asyncio
import uuid
from collections import deque

from dsh.core.abort import AbortController, AbortSignal
from dsh.core.cancellation import subscribe_abort
from dsh.core.session.json import UNDEFINED
from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.json_text import stringify_json
from dsh.typert.current import CurrentRemoteEvents
from dsh.typert.dispatch import TypertGatewayError
from dsh.typert.remote_events import lossless
from dsh.typert.rpc_result import absent
from dsh.typert.event_protocol import parse_result
from dsh.typert.access import event_resources
from dsh.typert.stores import field


class PeerEventQueue:
    def __init__(self):
        self.frames, self.closed, self.waiter = deque(), False, None

    def _wake(self):
        if self.waiter is not None and not self.waiter.done():
            self.waiter.set_result(None)

    def push(self, frame):
        if not self.closed:
            self.frames.append(frame)
            self._wake()

    def end(self):
        if not self.closed:
            self.closed = True
            self._wake()

    async def iterate(self, signal):
        dispose = subscribe_abort(signal, lambda *_: self.end())
        try:
            while True:
                while self.frames and not signal.aborted:
                    yield self.frames.popleft()
                if self.closed or signal.aborted:
                    return
                pending = self.waiter = asyncio.get_running_loop().create_future()
                try:
                    await asyncio.shield(pending)
                finally:
                    if self.waiter is pending:
                        self.waiter = None
        finally:
            dispose()


class AuthorizedRemoteEvents(CurrentRemoteEvents):
    def register(self, source, host):
        if self.registration is not None:
            raise RuntimeError('typert gateway: forwarded Remote event source is already registered')
        controller = AbortController()
        stream = source(controller.signal)
        registration = dict(controller=controller, host=dict(home=host['home']))
        async def consume():
            try:
                try:
                    async for dispatch in stream:
                        if controller.signal.aborted:
                            if 'context' in dispatch:
                                dispatch['reject'](controller.signal.reason)
                            return
                        if 'context' in dispatch:
                            self.start(dispatch)
                        else:
                            self.broadcast(dispatch)
                    if not controller.signal.aborted:
                        raise RuntimeError('typert gateway: forwarded Remote event source ended unexpectedly')
                finally:
                    close = getattr(stream, 'aclose', None)
                    if close is not None:
                        await close()
            except Exception as error:
                if self.registration is registration and not controller.signal.aborted:
                    self.close_events(error)
                    self.registration = None
                    controller.abort(error)
        self.registration = registration
        registration['done'] = asyncio.create_task(consume())
        async def dispose():
            if self.registration is registration:
                self.registration = None
                error = RuntimeError('typert gateway: forwarded Remote event source was removed')
                controller.abort(error)
                self.close_events(error)
            await registration['done']
        return lambda: start_coroutine(dispose())

    async def open(self, payload, signal, peer):
        if type(payload) is not dict or set(payload) != {'args'} or type(payload['args']) is not dict or payload['args']:
            raise TypertGatewayError('arguments-invalid', '$events', 'forwarded Remote event stream requires an empty args object')
        registration = self.registration
        if registration is None:
            raise TypertGatewayError('service-unavailable', '$events', 'forwarded Remote event source is unavailable')
        lifetime = AbortController()
        cleanups = [subscribe_abort(item, lifetime.abort) for item in (signal, registration['controller'].signal, peer.signal)]
        client_id = str(uuid.uuid4())
        while client_id in self.clients:
            client_id = str(uuid.uuid4())
        client = dict(id=client_id, peer=peer, principal=peer.principal, answers=field(peer.principal, 'kind') == 'owner',
                      queue=PeerEventQueue(), signal=lifetime.signal, deliveries={})
        self.clients[client_id] = client
        if client['answers']:
            for pending in self.pending.values():
                self.deliver(pending, client)
        reader = client['queue'].iterate(lifetime.signal)
        try:
            yield dict(type='ready', clientId=client_id, host=registration['host'])
            async for frame in reader:
                yield frame
        finally:
            await reader.aclose()
            for dispose in cleanups:
                dispose()
            self.clients.pop(client_id, None)
            for pending in list(client['deliveries'].values()):
                self.remove_delivery(pending, client)
            client['queue'].end()

    @staticmethod
    def valid_name(frame):
        if not isinstance(frame.get('event'), str) or not frame['event']:
            raise TypeError('typert gateway: Remote event name must be a nonempty string')

    def broadcast(self, frame):
        self.valid_name(frame)
        try:
            if type(frame.get('args')) is not list:
                raise ValueError()
            lossless(frame['args'])
        except Exception:
            raise TypeError('typert gateway: Remote event {} arguments are not lossless JSON data'.format(stringify_json(frame['event'])))
        wire = dict(type='emit', event=frame['event'], args=frame['args'])
        resolved, resources = False, None
        for client in self.clients.values():
            if not client['answers']:
                if not resolved:
                    resources = event_resources(frame.get('resources'), frame['args'])
                    resolved = True
                if resources is None:
                    continue
                decision = self.ctx.remoteAccess.decide(dict(principal=client['principal'], action='event:' + frame['event'], resources=resources))
                if decision['kind'] == 'deny':
                    continue
            client['queue'].push(wire)

    def project_request(self, source):
        request = source['request']
        if type(request) is not dict or 'agent' not in request or request['agent'] is not source['context']['subject']:
            raise TypeError('api gateway: Remote event request must carry its scoped Agent directly')
        signal = request.get('signal', UNDEFINED)
        if not absent(signal) and not isinstance(signal, AbortSignal):
            raise TypeError('api gateway: Remote event request signal must be an AbortSignal')
        projected = {key: value for key, value in request.items() if key not in ('agent', 'signal')}
        try:
            lossless(projected)
        except Exception:
            raise TypeError('api gateway: Remote event request is not lossless JSON data')
        return projected, None if absent(signal) else signal

    def start(self, source):
        try:
            self.valid_name(source)
            context = self.event_identity(source)
            projected, signal = self.project_request(source)
            event_id = str(uuid.uuid4())
            while event_id in self.pending:
                event_id = str(uuid.uuid4())
            pending = dict(id=event_id, source=source, deliveries={}, release_signal=lambda: None,
                           frame=dict(type='waterfall', event=source['event'], eventId=event_id, agentId=context['identity'], request=projected))
            try:
                pending['release_context'] = source['context']['value'].effect(lambda: lambda: self.cancel(pending, self.context_released_error()), 'api-gateway: Remote event ' + stringify_json(source['event']))
            except Exception:
                source['resolve'](dict(kind='next'))
                return
            self.pending[event_id] = pending
            if signal is not None:
                abort = lambda *_: self.cancel(pending, self.cancelled_error(signal.reason))
                signal.addEventListener('abort', abort, dict(once=True))
                pending['release_signal'] = lambda: signal.removeEventListener('abort', abort)
                if signal.aborted:
                    abort()
                    return
            for client in self.clients.values():
                if client['answers']:
                    self.deliver(pending, client)
        except Exception as error:
            source['reject'](error)

    def result(self, payload, peer):
        if type(payload) is not dict or set(payload) != {'args'}:
            raise RuntimeError('typert gateway: Remote event result requires exactly one plain-object args field')
        value = parse_result(payload['args'])
        client = self.clients.get(value['clientId'])
        if client is None:
            raise RuntimeError('typert gateway: Remote event result identifies no active event stream')
        if client['peer'] is not peer:
            raise TypertGatewayError('interactions-forbidden', '$events/result', 'Remote event result belongs to another Peer')
        pending = self.pending.get(value['eventId'])
        if pending is None or client['id'] not in pending['deliveries']:
            return
        self.remove_delivery(pending, client)
        outcome = value['outcome']
        if outcome['kind'] == 'rejected':
            error = RuntimeError(outcome['error']['message'])
            for key, item in outcome['error'].items():
                setattr(error, key, item)
            self.cancel(pending, error)
        elif outcome['kind'] == 'result' or not pending['deliveries']:
            self.finish(pending)
            source = pending['source']
            source['resolve'](dict(kind='result', value=outcome.get('value', UNDEFINED)) if outcome['kind'] == 'result' else dict(kind='next'))

    def has_live_client(self):
        return any(client['answers'] and not client['signal'].aborted for client in self.clients.values())

    def pending_info(self):
        return [dict(event=pending['frame']['event'], agentId=pending['frame']['agentId']) for pending in self.pending.values()]
