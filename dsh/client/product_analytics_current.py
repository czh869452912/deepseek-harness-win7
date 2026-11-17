"""Application-owned Desktop analytics intake over the canonical Remote service."""
import asyncio
import time

from dsh.client.analytics_os_current import collectEnvironment
from dsh.cordis.awaiting import await_callback_result, start_coroutine
from dsh.cordis.schema import Schema as z
from dsh.cordis.utils import _UNDEFINED
from dsh.core.abort import AbortController
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.core.cleanup import CleanupPromise
from dsh.typert.remote import Remote, TypertRemoteService


class CurrentProductAnalytics(TypertRemoteService):
    inject=['deepseekAccount','productTelemetry']
    Config=z.object(dict(enabled=z.boolean().default(True).volatile(),appVersion=z.string(),
        environmentQueryTimeoutMillis=z.number().step(1).min(1).max(2147483647).default(5000),
        environmentQueryMaxOutputBytes=z.number().step(1).min(1).max(2147483647).default(16384)))

    def __init__(self,ctx,config):
        super().__init__(ctx,'productAnalytics')
        self.config=config;self.active=True
        self.environmentLifetime=AbortController();self.environment=None;self.listeners=set()
        async def dispose():
            self.active=False;self._changed();self.environmentLifetime.abort()
            if self.environment is not None:await self.environment
        ctx.effect(lambda:dispose)
        ctx.on('loader/volatile-update',self._changed)
        def settings(child):child.effect(lambda:child.settings.configure(dict(auto=False),ctx.fiber))
        ctx.inject(['settings'],settings)
        def event(session,event):
            if event['type']!='compaction/start':return
            self.report(dict(eventName='context_compression',timestamp=int(time.time()*1000),
                attributes=dict(session_id=session.id,trigger_type='manual' if event['data'].get('turn',_UNDEFINED) is None else 'auto')))
        ctx.on('session/event',event)

    def _changed(self,*args):
        for listener in tuple(self.listeners):listener()

    @Remote
    def enabled(self):return self.active and self.config['enabled'].get()

    @Remote(dict(mode='stream'))
    async def watchPolicy(self,signal):
        update=asyncio.Event();changed=update.set
        self.listeners.add(changed);unsubscribe=subscribe_abort(signal,lambda *_:changed())
        try:
            while self.active and not aborted(signal):
                yield self.enabled()
                await update.wait();update.clear()
        finally:
            self.listeners.discard(changed);unsubscribe()

    @Remote
    def report(self,event):return CleanupPromise(start_coroutine(self._report(event)))

    async def _report(self,event):
        if not self.enabled():return
        try:
            if self.environment is None:
                self.environment=CleanupPromise(start_coroutine(collectEnvironment(dict(
                    timeoutMillis=self.config['environmentQueryTimeoutMillis'],
                    maxOutputBytes=self.config['environmentQueryMaxOutputBytes'],signal=self.environmentLifetime.signal))))
            pending=self.ctx.get('deepseekAccount').getDeviceIdentity()
            async def identity():
                try:return await await_callback_result(pending)
                except Exception:return None
            identity=CleanupPromise(start_coroutine(identity()))
            environment,identity=await asyncio.gather(self.environment,identity)
            if not self.enabled():return
            metadata={key:value for key,value in environment.items() if key!='missing_fields'}
            missing=','.join(key+'='+environment['missing_fields'][key] for key in sorted(environment['missing_fields']))
            attributes=dict(event.get('attributes') or {});attributes.update(metadata)
            if missing:attributes['missing_fields']=missing
            for source,target in [('deviceId','device_id'),('userId','user_id')]:
                value=identity.get(source,_UNDEFINED) if isinstance(identity,dict) else _UNDEFINED
                if value is not _UNDEFINED:attributes[target]=value
            version=self.config.get('appVersion',_UNDEFINED)
            if version is not _UNDEFINED:attributes['app_version']=version
            record=dict(event,body=event['eventName'],attributes=attributes)
            self.ctx.get('productTelemetry').emit(record)
        except Exception as error:
            self.ctx.logger.warn('Product analytics submission failed',error)
