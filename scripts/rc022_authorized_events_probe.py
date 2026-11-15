"""Pair event generations and trusted result ownership with actual Source Gateway."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    base = dict(clientId='client', eventId='event', outcome=dict(kind='next'))
    values = [None, [], {}, dict(base), dict(base, extra=1)]
    for key in ('clientId', 'eventId'):
        for value in ('', None, 1):
            values.append(dict(base, **{key: value}))
    for outcome in (None, [], {}, dict(kind='next', value=1), dict(kind='result'),
                    dict(kind='result', value=None), dict(kind='result', value=[1, {'x': True}]),
                    dict(kind='result', value=-0.0), dict(kind='result', extra=True), dict(kind='unknown')):
        values.append(dict(base, outcome=outcome))
    for error in (None, [], {}, dict(name='', message=''), dict(name='Error', message=3),
                  dict(name='Error', message=''), dict(name='Custom', message='why', code='E', details={'a': 1}),
                  dict(name='Error', message='why', code=3), dict(name='Error', message='why', details=-0.0),
                  dict(name='Error', message='why', extra=1)):
        values.append(dict(base, outcome=dict(kind='rejected', error=error)))
    return values


def error_value(error):
    result = dict(name=getattr(error, 'name', 'TypeError' if isinstance(error, TypeError) else 'Error'), message=str(error))
    for key in ('code', 'details'):
        if hasattr(error, key): result[key] = getattr(error, key)
    return result


class PushSource:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.closed = False

    async def stream(self, signal):
        from dsh.core.cancellation import subscribe_abort
        dispose = subscribe_abort(signal, lambda *_: self.queue.put_nowait(None))
        try:
            while not signal.aborted:
                item = await self.queue.get()
                if item is None: return
                frame, accepted = item
                yield frame
                accepted.set_result(None)
        finally:
            dispose()
            self.closed = True

    async def push(self, frame):
        accepted = asyncio.get_running_loop().create_future()
        self.queue.put_nowait((frame, accepted))
        await asyncio.wait_for(accepted, 1)


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    from dsh.host.connection.peer import Peer
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.typert.remote_access import RemoteAccessService
    from dsh.typert.gateway_authorized import AuthorizedGatewayService
    from dsh.typert.event_protocol import parse_result
    from dsh.typert.rpc_result import absent
    rows = []
    for index, value in enumerate(cases()):
        try: result = dict(value=parse_result(value))
        except Exception as error: result = dict(error=error_value(error))
        rows.append(dict(name='protocol-' + str(index), **result))
    ctx = Context()
    await ctx.plugin(CurrentTypertRegistry)
    await ctx.plugin(RemoteAccessService)
    await ctx.plugin(AuthorizedGatewayService)
    gateway = ctx.typertGateway
    peers, streams, controls = [], [], []
    source = PushSource()
    unregister = None
    def peer(kind='owner', interactions='answer'):
        value = Peer(ctx, dict(principal=dict(kind=kind), interactions=interactions))
        peers.append(value)
        return value
    owner, other, guest, guest2, passive = peer(), peer(), peer('guest'), peer('guest'), peer(interactions='none')
    reads = [0]
    def resources(value, *_):
        reads[0] += 1
        return value
    ctx.remoteAccess.registerPolicy('guest', SimpleNamespace(bindings=lambda principal: [dict(resource=dict(kind='session', id='a'), role=dict(actions=['event:notice']))]))
    async def open_events(who, payload=None):
        control = AbortController()
        controls.append(control)
        class Input:
            returned = False
            def __aiter__(self): return self
            async def __anext__(self): raise AssertionError('event stream consumed uplink')
            async def aclose(self): self.returned = True
        uplink = Input()
        stream = await gateway.wireStream.open('$events', dict(args={}) if payload is None else payload, uplink, who, control.signal)
        streams.append(stream)
        ready = await stream.__anext__()
        await asyncio.sleep(0)
        return stream, ready, uplink.returned
    async def next_value(stream):
        try: return dict(done=False, value=await asyncio.wait_for(stream.__anext__(), 1))
        except StopAsyncIteration: return dict(done=True)
    async def answer(who, client_id, event_id, outcome, payload=None):
        value = await gateway.dispatch_rpc('$events/result', payload if payload is not None else dict(args=dict(clientId=client_id, eventId=event_id, outcome=outcome)), AbortController().signal, who)
        return {key: item for key, item in value.items() if not absent(item)}
    async def invoke(signal=UNDEFINED, context=None, request=None):
        settled = []
        subject = object()
        child = context if context is not None else ctx.extend({})
        req = dict(agent=subject, question='q')
        if signal is not UNDEFINED: req['signal'] = signal
        if request is not None: req.update(request)
        def resolve(value): settled.append({key: item for key, item in value.items() if not absent(item)})
        await source.push(dict(event='ask', request=req, context=dict(value=child, subject=subject, agentId='agent-a'), resolve=resolve, reject=lambda error: settled.append(dict(error=error_value(error)))))
        return settled
    try:
        for name, who, payload in [('passive', passive, {}), ('missing-source', owner, {'args': {}})]:
            try: await open_events(who, payload)
            except Exception as error: rows.append(dict(name=name, error=error_value(error)))
        unregister = gateway.registerRemoteEvents(source.stream, dict(home='/fixture', ignored=True))
        try: gateway.registerRemoteEvents(source.stream, dict(home='/other'))
        except Exception as error: rows.append(dict(name='duplicate-source', error=error_value(error)))
        for name, payload in [('missing-args', {}), ('extra-payload', dict(args={}, extra=True)), ('nonempty-args', dict(args=dict(x=1)))]:
            try: await open_events(owner, payload)
            except Exception as error: rows.append(dict(name=name, error=error_value(error)))
        gs, gr, released = await open_events(guest)
        gs2, gr2, _ = await open_events(guest2)
        rows.append(dict(name='guest-ready', host=gr['host'], type=gr['type'], live=gateway.hasLiveClient(), released=released))
        os, ready, _ = await open_events(owner)
        rows.append(dict(name='owner-ready', host=ready['host'], live=gateway.hasLiveClient()))
        for args, readers in [(['global', dict(private='whole')], None), (['b'], {'session': resources}), ([None], {'session': resources}), (['a', dict(private='whole')], {'session': resources})]:
            await source.push(dict(event='notice', args=args, **(dict(resources=readers) if readers is not None else {})))
        rows.append(dict(name='broadcasts', owner=[(await next_value(os))['value'] for _ in range(4)], guests=[(await next_value(gs))['value'], (await next_value(gs2))['value']], readerCalls=reads[0]))
        rows.append(dict(name='result-authorization', passive=await answer(passive, 'x', 'y', dict(kind='next')), guest=await answer(guest, gr['clientId'], 'y', dict(kind='next')), inactive=await answer(owner, 'x', 'y', dict(kind='next'))))
        settled = await invoke()
        frame = (await next_value(os))['value']
        snapshot = gateway.getPendingRemoteEvents()
        snapshot[0]['event'] = 'tampered'
        rows.append(dict(name='owner-waterfall', frame={k: v for k, v in frame.items() if k != 'eventId'}, pending=gateway.getPendingRemoteEvents(), settled=bool(settled)))
        rows.append(dict(name='foreign-result', result=await answer(other, ready['clientId'], frame['eventId'], dict(kind='result', value='foreign'))))
        os2, ready2, _ = await open_events(other)
        redelivery = (await next_value(os2))['value']
        first = await answer(owner, ready['clientId'], frame['eventId'], dict(kind='next'))
        rows.append(dict(name='next-waits', first=first, settled=bool(settled), sameEvent=redelivery['eventId'] == frame['eventId']))
        last = await answer(other, ready2['clientId'], frame['eventId'], dict(kind='next'))
        rows.append(dict(name='last-next', last=last, settled=list(settled), pending=gateway.getPendingRemoteEvents(), duplicate=await answer(owner, ready['clientId'], frame['eventId'], dict(kind='result', value='late'))))
        settled = await invoke()
        frame = (await next_value(os))['value']
        await next_value(os2)
        result = await answer(owner, ready['clientId'], frame['eventId'], dict(kind='result'))
        cancellation = (await next_value(os2))['value']
        rows.append(dict(name='result-cancels-others', result=result, settled=list(settled), cancellation=cancellation['type'], sameEvent=cancellation['eventId'] == frame['eventId']))
        settled = await invoke()
        frame = (await next_value(os))['value']
        await next_value(os2)
        result = await answer(other, ready2['clientId'], frame['eventId'], dict(kind='rejected', error=dict(name='Refusal', message='no', code='E_DENIED', details=dict(reason='fixture'))))
        cancellation = (await next_value(os))['value']
        rows.append(dict(name='rejection', result=result, settled=list(settled), cancellation=cancellation['type']))
        await os2.aclose()
        settled = await invoke()
        frame = (await next_value(os))['value']
        await os.aclose()
        replacement, replacement_ready, _ = await open_events(owner)
        redelivery = (await next_value(replacement))['value']
        old = await answer(owner, ready['clientId'], frame['eventId'], dict(kind='result', value=1))
        await answer(owner, replacement_ready['clientId'], frame['eventId'], dict(kind='result', value=dict(answer=7)))
        rows.append(dict(name='generation-reconnect', sameEvent=redelivery['eventId'] == frame['eventId'], old=old, settled=list(settled)))
        control = AbortController(); control.abort('preabort')
        settled = await invoke(control.signal)
        rows.append(dict(name='preaborted', settled=list(settled), listeners=len(control.signal._listeners), pending=gateway.getPendingRemoteEvents()))
        control = AbortController()
        settled = await invoke(control.signal)
        frame = (await next_value(replacement))['value']
        control.abort(RuntimeError('host cancelled'))
        cancellation = (await next_value(replacement))['value']
        rows.append(dict(name='cancelled', settled=list(settled), listeners=len(control.signal._listeners), sameEvent=cancellation['eventId'] == frame['eventId']))
        scope = await ctx.plugin(lambda child: None)
        settled = await invoke(context=scope.ctx)
        await next_value(replacement)
        await scope.dispose()
        cancellation = (await next_value(replacement))['value']
        rows.append(dict(name='context-disposal', settled=list(settled), cancellation=cancellation['type']))
        await source.push(dict(event='notice', args=['a'], resources={'session': resources}))
        await guest.dispose()
        # The denied broadcasts and waterfalls never entered either guest's queue.
        rows.append(dict(name='peer-revocation', revoked=await next_value(gs), survivor=(await next_value(gs2))['value']))
        await next_value(replacement)
        settled = await invoke()
        await next_value(replacement)
        await unregister(); unregister = None
        rows.append(dict(name='source-withdrawal', settled=list(settled), owner=await next_value(replacement), guest=await next_value(gs2), sourceClosed=source.closed, pending=gateway.getPendingRemoteEvents(), live=gateway.hasLiveClient()))
        try: await open_events(owner)
        except Exception as error: rows.append(dict(name='withdrawn-source', error=error_value(error)))
        disposed = peer(); await disposed.dispose()
        try: await open_events(disposed, {})
        except Exception as error: rows.append(dict(name='disposed-first', code=error.code))
        return rows
    finally:
        if unregister is not None: await unregister()
        for control in controls: control.abort()
        for stream in streams: await stream.aclose()
        for value in peers: await value.dispose()
        await ctx.fiber.dispose()


def prepare(output):
    path = output / 'cases.json'
    path.write_text(json.dumps(cases()), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_authorized_events.mts', 'Actual Gateway event source, owner/guest/passive Peer gates, per-frame resource filtering, trusted result Peer binding, multi-owner settlement, generation replay, abort/context/source cleanup and exact result protocol validation.', [Path(__file__).resolve(), ROOT/'dsh/typert/gateway_authorized.py', ROOT/'dsh/typert/authorized_events.py', ROOT/'dsh/typert/event_protocol.py'], prepare)
