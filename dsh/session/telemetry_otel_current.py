"""Feedback-authorized canonical Session logs over the Cordis otel service."""
import asyncio
import copy
import math
from types import SimpleNamespace

from dsh.cordis.awaiting import start_coroutine
from dsh.cordis.json_text import stringify_json
from dsh.cordis.schema import Schema as z
from dsh.cordis.service import Service
from dsh.cordis.utils import js_to_string, _js_number_value, _UNDEFINED
from dsh.core.cleanup import CleanupPromise
from dsh.core.session.current_session import CurrentSession
from dsh.host.url_current import _url
from dsh.identity.anonymous_user_id import get_or_create_anonymous_user_id
from dsh.session.telemetry_current import (SessionTelemetryCoordinator, is_feedback,
    DISABLED_FEEDBACK_WARNING, NON_CANONICAL_EVENT_WARNING)


class CurrentSessionTelemetryCoordinator(SessionTelemetryCoordinator):
    def capture_event(self, session, event):
        attributes={'session.id':str(session.id),'session.format_version':session.header.version,
            'event.type':event['type'],'event.seq':event['seq']}
        for field,key in [('cwd','session.cwd'),('parentSession','session.parent_id')]:
            value=getattr(session.header,field)
            if value is not None:attributes[key]=str(value) if field=='parentSession' else value
        if session.header.isSeeded:attributes['session.seed_length']=session.inheritedEventCount
        data,kind=event['data'],event['type']
        error=(kind=='turn/end' and data['reason']['kind']=='error'
            or kind=='tool/result' and data['message'].get('isError') is True)
        record=dict(sourceEvent=dict(sessionId=session.id,
            envelope=copy.deepcopy({key:value for key,value in event.items() if key!='data'})),
            channel='ledger',time=event['time'],severity='error' if error else 'info',
            attributes=attributes,body=copy.deepcopy(data))
        self.deliver(session,record,event['seq'])


class CurrentOpenTelemetrySessionBackend(Service):
    inject=['sessions','otel']
    Config=z.object(dict(mode=z.union(['FEEDBACK_ONLY','DISABLED']).default('FEEDBACK_ONLY'),
        exporter=z.any(),processor=z.any(),shutdownTimeoutMillis=z.number(),
        maxRequestBytes=z.number().step(1).min(1).max(4000000)))
    instrumentation_version='0.2.2-rc.3'
    app_version='0.2.2-rc.3'

    def __init__(self,ctx,config=None):
        config=config or {};mode=config.get('mode')
        if mode is None:mode='FEEDBACK_ONLY'
        if mode not in ('FEEDBACK_ONLY','DISABLED'):
            raise ValueError('session-telemetry-otel: unsupported mode '+stringify_json(mode))
        super().__init__(ctx,'sessionTelemetry')
        self.mode=mode;self.sharing='disabled' if mode=='DISABLED' else 'feedback-only'
        self.provider=None;self.deadline=3000
        if mode=='DISABLED':
            ctx.on('session/event',self.event);return
        exporter=dict(config.get('exporter') or {})
        url=exporter.get('url',_UNDEFINED)
        if url is _UNDEFINED or url=='':
            raise ValueError('session-telemetry-otel: exporter.url is required (the full OTLP logs endpoint)')
        if url is None:raise TypeError("Cannot read properties of null (reading 'length')")
        try:parsed=_url(js_to_string(url))
        except Exception:
            raise ValueError('session-telemetry-otel: exporter.url is not a valid URL: '+stringify_json(url)) from None
        if parsed['protocol'] not in ('http:','https:'):
            raise ValueError('session-telemetry-otel: exporter.url must be http(s), got '+parsed['protocol'])
        processor=config.get('processor')
        batch=(processor or {}).get('maxExportBatchSize',_UNDEFINED)
        if batch is not _UNDEFINED and (type(batch) not in (int,float) or not math.isfinite(_js_number_value(batch)) or batch<1 or int(batch)!=batch):
            raise ValueError('session-telemetry-otel: processor.maxExportBatchSize must be a positive integer, got '+js_to_string(batch))
        deadline=config.get('shutdownTimeoutMillis')
        if deadline is None:deadline=3000
        if type(deadline) not in (int,float) or not math.isfinite(_js_number_value(deadline)) or not 0<deadline<=2147483647:
            raise ValueError('session-telemetry-otel: shutdownTimeoutMillis must be a positive finite number no greater than 2147483647, got '+js_to_string(deadline))
        self.deadline=deadline
        selected=dict(scope=dict(name='@deepseek-ai/dsh-session-telemetry-otel',version=self.instrumentation_version),
            exporter=exporter,resourceAttributes={'service.name':'deepseek-harness','service.version':self.app_version,
                'user.id':get_or_create_anonymous_user_id()},
            onFailure=lambda message,error=None:ctx.logger.warn(message,error))
        if processor is not None:selected['processor']=processor
        if config.get('maxRequestBytes') is not None:selected['maxRequestBytes']=config['maxRequestBytes']
        self.provider=ctx.get('otel').createSessionLogReporter(selected)
        self.coordinator=CurrentSessionTelemetryCoordinator(ctx,
            SimpleNamespace(emit=self._export_record,shutdown=self.shutdown),dict(capture='on-demand',includeHistory=True))
        ctx.on('session/event',self.event);ctx.on('feedback/committed',self.committed)

    def _export_record(self,record):
        source=record.get('sourceEvent')
        if source is None:
            self.ctx.logger.warn('Session log record withheld: redaction removed sourceEvent');return
        self.provider.reportSessionLog(dict(sessionId=source['sessionId'],
            event=dict(source['envelope'],data=record['body']),severityNumber={'info':9,'warn':13,'error':17}[record['severity']],
            attributes=record['attributes']))

    def emit(self,record):pass

    def event(self,session,event):
        if not is_feedback(session,event):return
        if self.mode=='DISABLED':self.ctx.logger.warn(DISABLED_FEEDBACK_WARNING)
        elif session.eventAt(event['seq']) is not event:self.ctx.logger.warn(NON_CANONICAL_EVENT_WARNING)
        else:self.coordinator.captureSession(session,event['seq'])

    def committed(self,inspection):
        snapshot=copy.deepcopy(inspection);events=snapshot['events']
        if not events:return
        committed=events[-1]
        session=CurrentSession.fromRestore(snapshot['meta']['id'],events,snapshot['meta'],snapshot['inheritedEventCount'],
            'detached',projections=self.ctx.get('sessions').messageProjections)
        if is_feedback(session,committed):self.coordinator.captureSession(session,committed['seq'])

    def shutdown(self):
        async def finish():
            if self.provider is None:return
            pending=self.provider.shutdown()
            loop=asyncio.get_running_loop();expired=loop.create_future()
            def timeout():
                self.provider.stopPending()
                expired.set_exception(RuntimeError('session-telemetry-otel: provider shutdown exceeded '+js_to_string(self.deadline)+'ms'))
            timer=loop.call_later(self.deadline/1000,timeout)
            try:
                async def drain():await pending
                task=CleanupPromise(start_coroutine(drain())).task
                await asyncio.wait([task,expired],return_when=asyncio.FIRST_COMPLETED)
                if expired.done():await expired
                await task
            finally:
                timer.cancel()
                if not expired.done():expired.cancel()
        return CleanupPromise(start_coroutine(finish()))
