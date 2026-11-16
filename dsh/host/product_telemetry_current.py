"""Application-owned product event policy over the independent Cordis otel channel."""
import asyncio
import re

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.schema import Schema as z
from dsh.cordis.service import Service
from dsh.cordis.utils import _UNDEFINED
from dsh.core.abort import AbortController
from dsh.host.url_current import _url


def _positive():return z.number().step(1).min(1).max(2147483647)


class CurrentProductTelemetry(Service):
    inject=['otel']
    Config=z.object(dict(
        endpoint=z.string().default('https://dsh-otel-collector.deepseeksvc.com/v1/logs'),
        channel=z.string().min(1).default('dsh_otel_report'),
        serviceName=z.string().required(),serviceVersion=z.string().required(),
        compression=z.union(['none','gzip']),maxExportBatchSize=_positive().default(512),
        maxQueueSize=_positive().default(2048),scheduledDelayMillis=_positive().default(30000),
        timeoutMillis=_positive().default(15000),exportTimeoutMillis=_positive().default(20000),
        shutdownTimeoutMillis=_positive().default(21000)))

    def __init__(self,ctx,config):
        try:endpoint=_url(config['endpoint'])
        except Exception:
            raise ValueError('product-telemetry-otel: endpoint must be a valid HTTP(S) URL') from None
        if re.search(r'[^\t\x20-\x7e\x80-\xff]',config['channel']):
            raise ValueError('product-telemetry-otel: channel must be a valid HTTP header value')
        if endpoint['protocol'] not in ('http:','https:'):
            raise ValueError('product-telemetry-otel: endpoint must use HTTP or HTTPS')
        if config['maxExportBatchSize']>config['maxQueueSize']:
            raise ValueError('product-telemetry-otel: maxExportBatchSize must not exceed maxQueueSize')
        super().__init__(ctx,'productTelemetry')
        exporter=dict(url=config['endpoint'],headers={'x-channel':config['channel']},timeoutMillis=config['timeoutMillis'])
        compression=config.get('compression',_UNDEFINED)
        if compression is not _UNDEFINED:exporter['compression']='gzip' if compression=='gzip' else 'none'
        self.reporter=ctx.get('otel').createEventReporter(dict(exporter=exporter,
            resourceAttributes={'service.name':config['serviceName'],'service.version':config['serviceVersion']},
            scope=dict(name='@deepseek-ai/dsh-host-product-telemetry-otel'),
            processor={key:config[key] for key in ['maxExportBatchSize','maxQueueSize','scheduledDelayMillis','exportTimeoutMillis']},
            onFailure=lambda message,error=None:ctx.logger.warn(message,error)))
        async def dispose():
            cancellation=AbortController()
            def deadline():
                ctx.logger.warn('Product telemetry shutdown deadline exceeded; pending events may be lost')
                cancellation.abort(RuntimeError('Product telemetry shutdown deadline exceeded'))
            timer=asyncio.get_running_loop().call_later(config['shutdownTimeoutMillis']/1000,deadline)
            try:await await_callback_result(self.reporter.shutdown(cancellation.signal))
            finally:timer.cancel()
        ctx.effect(lambda:dispose)

    def emit(self,record):self.reporter.emit(record)
