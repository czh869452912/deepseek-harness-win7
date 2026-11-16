"""Caller-cancellable ordinary-event HTTP exporter (separate from Session retry)."""
import asyncio
import gzip
import random
import http.client
import urllib.request

from dsh.core.abort import AbortController, abort_reason_error
from dsh.core.cleanup import CleanupPromise
from dsh.cordis.awaiting import start_coroutine, await_callback_result
from dsh.core.cancellation import aborted, subscribe_abort
from dsh.llm.http_stream import open_stream
from dsh.llm.stream_bridge import OwnedStream, iter_chunks
from dsh.host.http_decode import decodeContentChunks
from dsh.session.otel_http_current import SessionHttpExporter, MAX_RESPONSE_BODY_SIZE, resolve_headers


class EventHttpExporter(SessionHttpExporter):
    def __init__(self, options, signal=None, environment=None):
        super().__init__(options, environment=environment)
        self.signal = signal

    async def _headers(self):
        headers = await resolve_headers(self.options)
        if self.options.get('userAgent') is not None:
            headers = {key:value for key,value in headers.items() if key.lower()!='user-agent'}
            headers['User-Agent'] = self.options['userAgent']
        elif not any(key.lower()=='user-agent' for key in headers):
            headers['User-Agent'] = 'got (https://github.com/sindresorhus/got)'
        if not any(key.lower()=='accept-encoding' for key in headers):
            headers['Accept-Encoding']='gzip, deflate, br, zstd'
        return headers

    async def _request(self, payload, headers, signal):
        request=urllib.request.Request(self.options['url'],data=payload,headers=headers,method='POST')
        def read(cancel):
            with open_stream(request,cancel,idle_timeout_ms=2147483647,redirect_policy='manual',
                raise_http_errors=False,tls_context=self.tls_context,proxy_policy='direct') as (response,chunks):
                yield dict(status=response.status,reason=str(response.reason),headers=dict(response.headers))
                size=0
                try:
                    def wire():
                        count=0
                        for chunk in chunks:count+=len(chunk);yield chunk
                        length=response.headers.get('content-length')
                        if length is not None and count<int(length) and response.status not in (204,205,304):
                            raise RuntimeError('The server aborted pending request')
                    coding=response.headers.get('content-encoding','').lower()
                    decoded=decodeContentChunks(wire(),[coding]) if coding in ('gzip','deflate','br','zstd') else wire()
                    for chunk in decoded:
                        size+=len(chunk)
                        if size>MAX_RESPONSE_BODY_SIZE:raise RuntimeError('Promise was canceled')
                        yield chunk
                except Exception as error:
                    if isinstance(error,RuntimeError):raise
                    if not aborted(signal):raise RuntimeError('The server aborted pending request') from None
                    raise
        stream=iter_chunks(OwnedStream(read,caller=signal))
        try:
            metadata=await stream.__anext__()
            async for _ in stream:pass
            return metadata
        finally:await stream.aclose()

    async def _run(self,payload):
        if aborted(self.signal):raise abort_reason_error(self.signal)
        await self._ensure_agent()
        headers=await self._headers()
        if aborted(self.signal):raise abort_reason_error(self.signal)
        if self.config['compression']=='gzip':
            payload=gzip.compress(payload,mtime=0)
            headers={key:value for key,value in headers.items() if key.lower()!='content-encoding'}
            headers['Content-Encoding']='gzip'
        controller=AbortController();unsubscribe=subscribe_abort(self.signal,lambda *_:controller.abort())
        timed_out=[False]
        def timeout():
            if not controller.signal.aborted:timed_out[0]=True;controller.abort()
        def abort_error():return RuntimeError('The operation was aborted due to timeout' if timed_out[0] else 'This operation was aborted.')
        timer=asyncio.get_running_loop().call_later(self.config['timeoutMillis']/1000,timeout)
        try:
            for attempt in range(6):
                if controller.signal.aborted:raise abort_error()
                try:response=await self._request(payload,headers,controller.signal)
                except Exception as failure:
                    if controller.signal.aborted:raise abort_error() from None
                    if isinstance(failure,http.client.RemoteDisconnected):raise RuntimeError('socket hang up') from None
                    raise
                status=response['status']
                if status<300:return
                if status<400:raise RuntimeError('OTLP collector returned HTTP '+str(status))
                error=RuntimeError('Request failed with status code '+str(status)+' ('+response['reason']+'): POST '+self.options['url'])
                if status not in (429,502,503,504) or attempt==5:raise error
                value=next((value for key,value in response['headers'].items() if key.lower()=='retry-after'),None)
                try:delay=float(value)*1000 if value is not None else 0
                except ValueError:
                    from dsh.session.otel_http_current import retry_after
                    delay=retry_after(value)
                if not delay:delay=min(2**attempt*1000,5000)+random.random()*100
                wake=asyncio.Event();remove=subscribe_abort(controller.signal,lambda *_:wake.set())
                try:
                    try:await asyncio.wait_for(wake.wait(),max(0,delay)/1000)
                    except asyncio.TimeoutError:pass
                finally:remove()
        finally:
            timer.cancel();unsubscribe()

    def shutdown(self):
        if self._shutdown is not None:return self._shutdown
        self.closed=True
        async def finish():
            try:await self.forceFlush()
            finally:
                destroy=getattr(self._selected_agent,'destroy',None)
                if destroy is not None:await await_callback_result(destroy())
        self._shutdown=CleanupPromise(start_coroutine(finish()))
        return self._shutdown
