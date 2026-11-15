"""Current list handles, summary-only hints and cooperative row work."""
import asyncio
import time

from dsh.api.session_list_current import CurrentSessionList, metadata_schema, image_limits_schema
from dsh.api.session_list import list_metadata
from dsh.api.session_commands_current import error_text


class AuthorizedSessionList(CurrentSessionList):
    def __init__(self, ctx, work_slice_ms=16):
        self.ctx, self.work_slice_ms = ctx, work_slice_ms
        self.list_metadata = None

    async def initialize(self):
        self.list_metadata = await self.ctx.get('sessionProjections').register(dict(
            key='sessionListMetadata', stateVersion=1, stateSchema=metadata_schema,
            init=lambda *_: dict(blank=True, lastPromptAt=None), apply=list_metadata,
            wire=dict(viewSchema=metadata_schema, view=lambda state: state)))
        def null_schema(value):
            if value is not None:
                raise ValueError('image limits state must be null')
            return None
        await self.ctx.get('sessionProjections').register(dict(
            key='imageLimits', stateVersion=1, stateSchema=null_schema,
            init=lambda *_: None, apply=lambda state, _: state,
            wire=dict(viewSchema=image_limits_schema, view=lambda _: self.ctx.get('attachments').imageLimits, summary=False)))

    def projections_for(self, header, session=None):
        try:
            keys = self.ctx.get('sessionProjections').summaryKeys()
            if session is not None:
                block = self.ctx.get('sessionProjections').snapshot(session, keys)
                kind = 'sequenced'
            else:
                cache = self.ctx.get('sessionProjectionCache')
                block = None if cache is None else cache.cachedSnapshot(header, keys) or cache.cachedPredecessorTitle(header)
                kind = 'cached'
            return dict(kind=kind, asOfSeq=block['asOfSeq'], values=block['values']) if block is not None and block['values'] else None
        except Exception as error:
            self.ctx.logger.warn('api-session.list: projection column for "{}" failed; serving the row without it: {}'.format(header.id, error_text(error)))
            return None

    def _summary(self, header, session=None, format_status=None):
        # Attached metadata is read from its own handle even if another wire view fails.
        metadata = self.list_metadata.stateOf(session) if session is not None else None
        projections = self.projections_for(header, session)
        if session is None:
            metadata = (projections or {}).get('values', {}).get('sessionListMetadata')
        agent = self.ctx.get('agents').get(header.id) if session is not None else None
        value = dict(sessionId=header.id, updatedAt=max(header.createdAt, metadata['lastPromptAt'] or 0 if metadata is not None else 0),
            agentAvailable=agent is not None and agent.session is session,
            running=agent is not None and agent.status=='running', blank=metadata['blank'] if metadata is not None else False)
        if session is not None:
            value['formatStatus'] = 'current'
        elif format_status is not None:
            value['formatStatus'] = format_status
        for key, field in (('parentSessionId', header.parentSession), ('origin', header.origin), ('cwd', header.cwd), ('projections', projections)):
            if field is not None:
                value[key] = field
        return value

    async def list(self, signal=None):
        if signal is not None:
            signal.throwIfAborted()
        records = await self.ctx.get('sessionQuery').listSessions(signal)
        if signal is not None:
            signal.throwIfAborted()
        items, cold = [], []
        deadline = time.perf_counter() + self.work_slice_ms / 1000.0
        for record in records:
            if signal is not None:
                signal.throwIfAborted()
            live = self.ctx.get('sessions').get(record['header'].id)
            if live is not None:
                items.append(self.summaryFor(live))
            elif record['header'].cwd is not None:
                cold.append(record)
            if time.perf_counter() >= deadline:
                await asyncio.sleep(0)
                if signal is not None:
                    signal.throwIfAborted()
                deadline = time.perf_counter() + self.work_slice_ms / 1000.0
        for record in cold:
            if signal is not None:
                signal.throwIfAborted()
            items.append(self._summary(record['header'], format_status=record.get('formatStatus')))
            if time.perf_counter() >= deadline:
                await asyncio.sleep(0)
                if signal is not None:
                    signal.throwIfAborted()
                deadline = time.perf_counter() + self.work_slice_ms / 1000.0
        if signal is not None:
            signal.throwIfAborted()
        return sorted(items, key=lambda value: -value['updatedAt'])
