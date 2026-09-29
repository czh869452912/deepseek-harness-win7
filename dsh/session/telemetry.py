"""Consent-gated canonical-log capture using the Python 3.8 OpenTelemetry SDK."""
import asyncio
import copy
import logging
import math
import threading
import time
import weakref
from urllib.parse import urlsplit

from dsh.cordis.service import Service
from dsh.identity.anonymous_user_id import get_or_create_anonymous_user_id

_HANDOFF = weakref.WeakKeyDictionary()
LOG = logging.getLogger('session-telemetry')


class OpenTelemetrySessionBackend(Service):
    inject = ['sessions']

    def __init__(self, ctx, config=None):
        config = config or {}
        mode = config.get('mode', 'DISABLED')
        if mode not in ('DISABLED', 'FULL', 'FEEDBACK_ONLY'):
            raise ValueError('session-telemetry-otel: unsupported mode ' + str(mode))
        super().__init__(ctx, 'sessionTelemetry')
        self.mode = mode
        self.sharing = {'FULL': 'full', 'FEEDBACK_ONLY': 'feedback-only', 'DISABLED': 'disabled'}[mode]
        self.provider, self.closed, self.adopted, self.seen = None, False, set(), weakref.WeakKeyDictionary()
        self.deadline = config.get('shutdownTimeoutMillis', 3000)
        if mode == 'DISABLED':
            ctx.on('session/event', self.event)
            return
        exporter = dict(config.get('exporter') or {})
        url = urlsplit(exporter.pop('url', ''))
        if url.scheme not in ('http', 'https') or not url.netloc:
            raise ValueError('session-telemetry-otel: exporter.url must be a full http(s) logs endpoint')
        if type(self.deadline) not in (int, float) or not math.isfinite(self.deadline) or not 0 < self.deadline <= 2147483647:
            raise ValueError('session-telemetry-otel: invalid shutdownTimeoutMillis')
        processor = dict(config.get('processor') or {})
        batch = processor.get('maxExportBatchSize')
        if batch is not None and (type(batch) is not int or batch < 1):
            raise ValueError('processor.maxExportBatchSize must be a positive integer')
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http import Compression
        # SDK naming/units differ between Node and Python; reject unhandled
        # options instead of silently pretending to pass them through.
        options = dict(endpoint=url.geturl())
        for key, value in exporter.items():
            if key == 'timeoutMillis':
                options['timeout'] = value / 1000
            elif key == 'headers':
                options['headers'] = value
            elif key == 'compression':
                options['compression'] = Compression.Gzip if value in ('gzip', 1) else Compression.NoCompression if value in ('none', 0) else Compression(value)
            elif key == 'keepAlive' and value is True:
                pass  # requests.Session is the SDK's persistent connection pool.
            else:
                raise ValueError('Python OTel exporter does not support option: ' + key)
        mapping = dict(maxExportBatchSize='max_export_batch_size', maxQueueSize='max_queue_size', scheduledDelayMillis='schedule_delay_millis', exportTimeoutMillis='export_timeout_millis')
        if any(key not in mapping for key in processor):
            raise ValueError('unsupported Python OTel processor option')
        self.provider = LoggerProvider(resource=Resource({'service.name': 'DeepSeek Harness', 'service.version': '0.1.2-alpha.1', 'user.id': get_or_create_anonymous_user_id()}), shutdown_on_exit=False)
        self.provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(**options), **{mapping[key]: value for key, value in processor.items()}))
        self.loggers = {channel: self.provider.get_logger('@deepseek-ai/dsh-session-telemetry-otel' + ('/ops' if channel == 'ops' else ''), '0.1.2-alpha.1') for channel in ('ledger', 'ops')}
        ctx.effect(lambda: self.shutdown)
        ctx.on('session/event', self.event)
        if mode == 'FULL':
            ctx.on('session/created', self.adopt)
            ctx.on('session/disposed', self.disposed)
            ctx.on('agent/error', self.agent_error)
            for session in ctx.get('sessions').list():
                self.adopt(session)

    def enqueue(self, record):
        from opentelemetry.sdk._logs import LogRecord
        from opentelemetry._logs import SeverityNumber
        record = self.ctx.waterfall_sync('session-telemetry/record', copy.deepcopy(record), lambda value: value)
        severity = record['severity'].upper()
        stamp = int(record['time'] * 1000000)
        self.loggers[record['channel']].emit(LogRecord(timestamp=stamp, observed_timestamp=stamp, trace_id=0, span_id=0, trace_flags=0, severity_text=severity,
            severity_number=getattr(SeverityNumber, severity), body=record['body'], attributes=record['attributes'], resource=self.provider.resource))

    def emit(self, record):
        if self.mode == 'FULL' and not self.closed:
            self.enqueue(record)

    def capture(self, session, through=None):
        seen = self.seen.setdefault(session, set())
        cursor = _HANDOFF.get(session, session.firstLiveSeq - 1)
        for event in session.events:
            if through is not None and event['seq'] > through:
                break
            try:
                if event['type'] == 'assistant/chunk':
                    key = (event['data']['turn'], event['data']['step'])
                    duplicate = key in seen
                    seen.add(key)
                    if duplicate:
                        continue
                if event['seq'] <= cursor:
                    continue
                attributes = {'session.id': session.id, 'event.type': event['type'], 'event.seq': event['seq']}
                for field, key in [('cwd', 'session.cwd'), ('parentSession', 'session.parent_id'), ('seedLength', 'session.seed_length')]:
                    value = getattr(session.header, field)
                    if value is not None:
                        attributes[key] = value
                data, kind = event['data'], event['type']
                error = kind == 'turn/end' and data.get('reason', {}).get('kind') == 'error'
                if kind == 'tool/result':
                    blocks = data.get('message', {}).get('content', [])
                    error = bool(blocks and blocks[0].get('isError'))
                self.enqueue(dict(channel='ledger', time=event['time'], severity='error' if error else 'info', attributes=attributes, body=copy.deepcopy(data)))
                _HANDOFF[session] = event['seq']
            except Exception:
                LOG.warning('telemetry capture failed', exc_info=True)

    def event(self, session, event):
        if self.closed:
            return
        if self.mode == 'FULL':
            self.capture(session, event['seq'])
        elif event['type'] == 'feedback/record':
            if self.mode == 'DISABLED':
                LOG.warning('session telemetry is DISABLED; nothing will be shared and this feedback remains local')
            elif 0 <= event['seq'] < len(session.events) and session.events[event['seq']] is event:
                self.capture(session, event['seq'])
            else:
                LOG.warning('session telemetry ignored a feedback event absent from the canonical session log')

    def adopt(self, session):
        if session not in self.adopted:
            self.adopted.add(session)
            self.capture(session)

    def operational(self, session, op, body, severity='info', extra=None):
        try:
            self.enqueue(dict(channel='ops', time=int(time.time() * 1000), severity=severity,
                attributes=dict({'telemetry.op': op, 'session.id': session.id}, **(extra or {})), body=body))
        except Exception:
            LOG.warning('telemetry operational capture failed', exc_info=True)

    def disposed(self, session):
        if session in self.adopted:
            self.adopted.remove(session)
            self.operational(session, 'shutdown', dict(op='shutdown'))

    def agent_error(self, value):
        error, agent = value['error'], value['agent']
        name = type(error).__name__
        self.operational(agent.session, 'agent-error', dict(name=name, message=str(error)), 'error',
                         {'agent.id': agent.id, 'error.name': name, 'turn': value['turn'], 'step': value['step']})

    async def shutdown(self):
        if self.closed or self.provider is None:
            return
        self.closed = True
        for session in list(self.adopted):
            self.disposed(session)
        # An outer deadline must also bound the SDK's pre-export drain.
        finished, failures = threading.Event(), []
        def stop():
            try:
                self.provider.shutdown()
            except Exception as error:
                failures.append(error)
            finally:
                finished.set()
        threading.Thread(target=stop, name='dsh-telemetry-shutdown', daemon=True).start()
        deadline = time.monotonic() + self.deadline / 1000
        while not finished.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        if not finished.is_set() or failures:
            LOG.warning('telemetry backend shutdown failed or exceeded %sms', self.deadline)
