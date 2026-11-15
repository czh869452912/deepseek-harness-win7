"""Open one exact snapshot, then consume uncovered durable and Assistant frames."""
from dsh.api.session_history_authorized import (
    resolve_history_request, validate_observation_address, history, projections,
)
from dsh.api.session_history_current import address_id, not_found
from dsh.api.session_listeners import ListenerBuffer, EventListener
from dsh.typert.remote import remote_error_of


class SessionWebController:
    def __init__(self, ctx, history_controller, promote):
        self.ctx, self.history_controller, self.promote = ctx, history_controller, promote

    async def follow(self, request, signal):
        sid = address_id(request['address'])
        spec = resolve_history_request(request)
        queue = ListenerBuffer(self.ctx, signal)
        listener = assistant = observation = source = None
        try:
            listener = EventListener(self.ctx, sid, signal, queue)
            if request.get('assistantStream') is True:
                assistant = self.history_controller.streamsListener.bind(sid, signal, queue)
            try:
                observation = await self.history_controller.usingObservation(dict(sessionId=sid, projection=True), signal)
            except Exception as error:
                remote = remote_error_of(error)
                if remote is not None and remote['code'] == 'session/not-found':
                    raise not_found(request['address']) from None
                raise
            validate_observation_address(request['address'], observation)
            opening = dict(type='snapshot', header=observation.header.to_dict(),
                           projections=projections(observation), **history(observation, spec))
            listener.setCursor(opening['cursor'])
            if assistant is not None:
                current = assistant.snapshot()
                opening['assistantStream'] = current['baseline']
                assistant.setOrdinalCut(current['ordinal'])
            if (request.get('activate') is True and not signal.aborted and
                observation.header.origin != 'subagent' and observation.source == 'prepared'):
                promotion = observation.retain()
                observation.dispose()
                try:
                    self.promote(promotion)
                except BaseException:
                    promotion.dispose()
                    raise
            else:
                observation.dispose()
            observation = None
            yield opening
            source = queue.items()
            async for item in source:
                yield item
        finally:
            if source is not None:
                await source.aclose()
            if observation is not None:
                observation.dispose()
            if assistant is not None:
                assistant.dispose()
            if listener is not None:
                listener.dispose()
            queue.dispose()
