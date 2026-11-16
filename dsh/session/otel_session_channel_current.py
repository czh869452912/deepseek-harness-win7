"""Independent byte/count-bounded Session-log channel over an owned exporter."""
import asyncio
import copy

from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.core.cleanup import CleanupPromise
from dsh.session.otel_records_current import resolve_session_log_limits, session_log_record
from dsh.session.otel_wire_current import serialize_records


class SessionLogReporter:
    def __init__(self, options, exporter):
        self.limit = resolve_session_log_limits(options)
        self.options = dict(options, scope=dict(options['scope']), resourceAttributes=dict(options['resourceAttributes']))
        self.exporter = exporter
        self.config = dict(maxQueueSize=2048, maxExportBatchSize=512,
                           scheduledDelayMillis=1000, exportTimeoutMillis=30000)
        self.config.update(options.get('processor') or {})
        self.queue = []
        self.bytes = 0
        self.timer = None
        self.active = None
        self._shutdown = None
        self.stopped = False
        self.closed = False

    def _warn(self, message, error=None):
        self.options['onFailure'](message, error)

    def _serialize(self, records):
        return serialize_records(records, self.options['scope'], self.options['resourceAttributes'], session=True)

    def reportSessionLog(self, record):
        if self.closed or self.stopped: return
        # Logger emission precedes processor queue admission in the SDK.
        emitted = session_log_record(record)
        if len(self.queue) >= self.config['maxQueueSize']:
            self._warn('Session log queue is full; record rejected')
            return
        try:
            emitted = copy.deepcopy(emitted)
            size = len(self._serialize([emitted]))
        except Exception as error:
            self._warn('Session log serialization failed; record rejected', error)
            return
        if size > self.limit:
            self._warn('Session log record rejected; content was not truncated',
                       ValueError('Session log record exceeds maxRequestBytes: '+str(size)+' > '+str(self.limit)))
            return
        self.queue.append((emitted, size))
        self.bytes += size
        if self.active is not None: return
        if len(self.queue) >= self.config['maxExportBatchSize'] or self.bytes >= self.limit:
            self.forceFlush()
        elif self.timer is None:
            self.timer = asyncio.get_running_loop().call_later(self.config['scheduledDelayMillis']/1000, self.forceFlush)

    def forceFlush(self):
        if self.timer is not None: self.timer.cancel(); self.timer = None
        if self.active is not None: return self.active
        if not self.queue:
            result = asyncio.get_running_loop().create_future(); result.set_result(None); return result
        self.active = CleanupPromise(start_coroutine(self._drain()))
        return self.active

    async def _drain(self):
        try:
            while not self.stopped and self.queue:
                size, count = 0, 0
                for _, measured in self.queue:
                    if count == self.config['maxExportBatchSize'] or size+measured > self.limit: break
                    size += measured; count += 1
                records = [record for record, _ in self.queue[:count]]
                del self.queue[:count]; self.bytes -= size
                loop = asyncio.get_running_loop()
                watchdog = loop.call_later(self.config['exportTimeoutMillis']/1000, self._warn,
                    'Session log request exceeded exportTimeoutMillis; waiting for transport settlement')
                try:
                    try: await await_callback_result(self.exporter.export(self._serialize(records)))
                    except Exception as error: self._warn('Session log export failed', error)
                finally: watchdog.cancel()
                # Even a synchronous exporter failure settles across the
                # Promise await boundary before another batch can start.
                await asyncio.sleep(0)
                flush = getattr(self.exporter, 'forceFlush', None)
                if flush is not None: await await_callback_result(flush())
        finally: self.active = None

    def stopPending(self):
        self.stopped = True
        self.queue.clear(); self.bytes = 0
        if self.timer is not None: self.timer.cancel(); self.timer = None

    def shutdown(self):
        if self._shutdown is not None: return self._shutdown
        self.closed = True
        async def finish():
            await self.forceFlush()
            await await_callback_result(self.exporter.shutdown())
        self._shutdown = CleanupPromise(start_coroutine(finish()))
        return self._shutdown
