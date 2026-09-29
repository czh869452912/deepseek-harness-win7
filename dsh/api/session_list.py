"""Bounded cold summaries; list reads never activate an Agent."""
import asyncio
import os


def list_metadata(state, event):
    blank = state['blank'] and event['type'] != 'turn/start'
    at = event['time'] if event['type'] == 'user/message' and event['data']['source']['kind'] == 'user' else state['lastPromptAt']
    return state if blank == state['blank'] and at == state['lastPromptAt'] else dict(blank=blank, lastPromptAt=at)


class SessionList:
    def __init__(self, ctx, maximum=1024):
        self.ctx, self.maximum = ctx, maximum
        projections = ctx.get('sessionProjections')
        projections.register(dict(key='sessionListMetadata', stateVersion=1, stateSchema=lambda value: value,
                                 init=lambda _: dict(blank=True, lastPromptAt=None), apply=list_metadata,
                                 wire=dict(viewSchema=lambda value: value, view=lambda value: value)))
        projections.register(dict(key='imageLimits', stateVersion=1, stateSchema=lambda value: value,
                                 init=lambda _: None, apply=lambda state, _: state,
                                 wire=dict(viewSchema=lambda value: value, view=lambda _: ctx.get('attachments').image_limits)))

    def projections(self, header, session=None):
        try:
            registry = self.ctx.get('sessionProjections' if session is not None else 'sessionProjectionCache')
            value = registry.cachedSnapshot(session if session is not None else header) if registry is not None else None
            return value if value is not None and value['values'] else None
        except Exception as error:
            self.ctx.logger.warn('api-session.list: projection column unavailable: ' + str(error))
            return None

    def summary(self, header, live=None, projections=None):
        metadata = (projections or {}).get('values', {}).get('sessionListMetadata', {})
        agent = self.ctx.get('agents').get(header.id) if live is not None else None
        value = dict(sessionId=header.id, updatedAt=max(header.createdAt, metadata.get('lastPromptAt') or 0),
                     running=agent is not None and agent.status == 'running', blank=metadata.get('blank', live.seq == 0 if live is not None else False))
        for key, content in [('parentSessionId', header.parentSession), ('origin', header.origin), ('cwd', header.cwd), ('projections', projections)]:
            if content is not None:
                value[key] = content
        return value

    def summary_for(self, session):
        return self.summary(session.header, session, self.projections(session.header, session))

    async def cold(self, header, signal):
        projections = self.projections(header)
        if (projections or {}).get('values', {}).get('sessionListMetadata', {}).get('blank') is not False and self.maximum:
            persistence = self.ctx.get('sessionPersistence')
            location = persistence.locate(header) if persistence is not None else None
            if location is not None:
                signal.throw_if_aborted()
                try:
                    path = location['path'] if isinstance(location, dict) else location.path
                    if os.stat(path).st_size <= self.maximum:
                        source = await self.ctx.get('sessionQuery').observeSession(header.id, dict(signal=signal, projectionMode='all'))
                        try:
                            projections = source.projections or projections
                        finally:
                            source.dispose()
                except Exception as error:
                    signal.throw_if_aborted()
                    self.ctx.logger.warn('api-session.list: small cold observation unavailable: ' + str(error))
        raced = self.ctx.get('sessions').get(header.id)
        return self.summary_for(raced) if raced is not None else self.summary(header, projections=projections)

    async def list(self, signal):
        signal.throw_if_aborted()
        records = await self.ctx.get('sessionQuery').listSessions(signal)
        signal.throw_if_aborted()
        items, cold = [], []
        for record in records:
            header = record['header']
            live = self.ctx.get('sessions').get(header.id)
            if live is not None:
                items.append(self.summary_for(live))
            elif header.cwd is not None:
                cold.append(header)
        for offset in range(0, len(cold), 16):
            items.extend(await asyncio.gather(*(self.cold(header, signal) for header in cold[offset:offset + 16])))
        return sorted(items, key=lambda item: -item['updatedAt'])
