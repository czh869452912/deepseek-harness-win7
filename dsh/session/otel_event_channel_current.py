"""Independent ordinary-event count batching over a caller-owned exporter."""
import asyncio
import copy
import math
import time

from dsh.cordis.awaiting import await_callback_result, start_coroutine
from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.core.cleanup import CleanupPromise
from dsh.session.otel_event_http_current import EventHttpExporter
from dsh.session.otel_records_current import event_log_record
from dsh.session.otel_wire_current import serialize_records


def _timer_delay(value):
    number=float(value)
    return (int(number) if math.isfinite(number) and 1<=number<=2147483647 else 1)/1000


class EventLogReporter:
    def __init__(self, options, exporter=None, clock=None):
        self.options=dict(options,scope=dict(options['scope']),resourceAttributes=dict(options['resourceAttributes']))
        self.clock=clock or (lambda:time.time()*1000)
        self.cancellation=AbortController()
        self.exporter=exporter if exporter is not None else EventHttpExporter(options['exporter'],self.cancellation.signal)
        supplied=options.get('processor') or {}
        self.config={key:supplied.get(key) if supplied.get(key) is not None else default
            for key,default in [('maxQueueSize',2048),('maxExportBatchSize',512),
                ('scheduledDelayMillis',1000),('exportTimeoutMillis',30000)]}
        if self.config['maxExportBatchSize']>self.config['maxQueueSize']:
            self.config['maxExportBatchSize']=self.config['maxQueueSize']
        self.queue=[];self.timer=None;self.current=None;self.flushing=False;self.closed=False
        self._provider_shutdown=None;self._export_shutdown=None

    def emit(self, record):
        if self.closed:return
        selected=copy.deepcopy(event_log_record(record,self.clock()))
        if len(self.queue)>=self.config['maxQueueSize']:return
        self.queue.append(selected);self._schedule()

    def _clear_timer(self):
        if self.timer is not None:self.timer.cancel();self.timer=None

    def _schedule(self):
        if self.closed or self.flushing or not self.queue or self.current is not None:return
        if len(self.queue)>=self.config['maxExportBatchSize']:self._one_batch()
        elif self.timer is None:
            self.timer=asyncio.get_running_loop().call_later(_timer_delay(self.config['scheduledDelayMillis']),self._one_batch)

    async def _operation(self, records):
        # SDK resource readiness always creates an await boundary before export.
        await asyncio.sleep(0)
        async def send():
            try:
                payload=serialize_records(records,self.options['scope'],self.options['resourceAttributes'])
                await await_callback_result(self.exporter.export(payload))
            except Exception as error:self.options['onFailure']('Product telemetry export failed',error)
        request=CleanupPromise(start_coroutine(send()))
        # Processor timeout settles only the processor operation. The exporter
        # continues owning its request and reports a later transport failure.
        await asyncio.wait([request.task],timeout=_timer_delay(self.config['exportTimeoutMillis']))

    def _one_batch(self):
        self._clear_timer()
        if not self.queue:return
        count=int(self.config['maxExportBatchSize'])
        records=self.queue[:count];del self.queue[:count]
        operation=CleanupPromise(start_coroutine(self._operation(records)));self.current=operation
        def settled(_):
            self.current=None;self._schedule()
        operation.add_done_callback(settled)

    async def _flush_exporter(self):
        flush=getattr(self.exporter,'forceFlush',None)
        if flush is not None:await await_callback_result(flush())

    async def _flush_all(self):
        if self.flushing:return
        self.flushing=True
        selected=self.queue;self.queue=[];self._clear_timer()
        try:
            current=self.current
            if current is not None:
                await self._flush_exporter();await current;self.current=None
            while selected:
                count=int(self.config['maxExportBatchSize'])
                records=selected[:count];del selected[:count]
                current=CleanupPromise(start_coroutine(self._operation(records)));self.current=current
                await asyncio.sleep(0)
                await self._flush_exporter();await current;self.current=None
        finally:
            self.flushing=False;self._schedule()

    def _shutdown_exporter(self):
        if self._export_shutdown is None:
            async def finish():await await_callback_result(self.exporter.shutdown())
            self._export_shutdown=CleanupPromise(start_coroutine(finish()))
        return self._export_shutdown

    def shutdown(self, signal=None):
        unsubscribe=subscribe_abort(signal,lambda *_:self.cancellation.abort(getattr(signal,'reason',None)))
        if self._provider_shutdown is None:
            self.closed=True
            async def provider():
                await self._flush_all();await self._shutdown_exporter()
            self._provider_shutdown=CleanupPromise(start_coroutine(provider()))
        async def finish():
            try:await self._provider_shutdown
            finally:
                try:await self._shutdown_exporter()
                finally:unsubscribe()
        return CleanupPromise(start_coroutine(finish()))
