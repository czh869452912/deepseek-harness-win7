"""Explicit Session-log HTTP exporter, independent of ambient collector identity."""
import asyncio
import datetime
import email.utils
import errno
import gzip
import http.client
import math
import os
import random
import re
import socket
import ssl
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dsh.cordis.awaiting import await_callback_result, start_coroutine
from dsh.cordis.utils import js_to_string, _js_number_value
from dsh.core.cleanup import CleanupPromise
from dsh.host.http_proxy_policy import JS_SPACE
from dsh.llm.http_stream import open_stream
from dsh.llm.stream_bridge import OwnedStream, iter_chunks

MAX_RESPONSE_BODY_SIZE = 4194304
DEFAULT_USER_AGENT = 'OTel-OTLP-Exporter-JavaScript/0.222.0'


class _RetryableTransportError(Exception):
    def __init__(self, error): self.error = error


def _env_number(value):
    if not isinstance(value, str): return None
    value = value.strip(JS_SPACE)
    if not value: return None
    try:
        if re.fullmatch(r'0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+', value): number = float(int(value, 0))
        elif re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', value): number = float(value)
        else: return None
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, OverflowError): return None


def log_transport_options(options, environment=None):
    env = os.environ if environment is None else environment
    timeout = options.get('timeoutMillis')
    if timeout is None:
        timeout = (_env_number(env.get('OTEL_EXPORTER_OTLP_LOGS_TIMEOUT'))
            or _env_number(env.get('OTEL_EXPORTER_OTLP_TIMEOUT')) or 10000)
    number = _js_number_value(timeout) if type(timeout) in (int, float) else None
    if number is None or not math.isfinite(number) or number <= 0:
        raise ValueError("Configuration: timeoutMillis is invalid, expected number greater than 0 (actual: '"+js_to_string(timeout)+"')")
    compression = options.get('compression')
    if compression is None:
        compression = 'none'
        for name in ('OTEL_EXPORTER_OTLP_LOGS_COMPRESSION', 'OTEL_EXPORTER_OTLP_COMPRESSION'):
            value = env.get(name)
            value = value.strip(JS_SPACE) if isinstance(value, str) else None
            if value in ('none', 'gzip'):
                compression = value; break
    return dict(timeoutMillis=timeout, compression=compression,
        concurrencyLimit=options.get('concurrencyLimit') if options.get('concurrencyLimit') is not None else 30)


async def resolve_headers(options):
    selected = options.get('headers')
    if callable(selected): selected = await await_callback_result(selected())
    headers = {'Content-Type': 'application/json'}
    headers.update(selected or {})
    return headers


def retry_after(value):
    if value is None: return None
    match = re.match(r'^[\s]*([+-]?[0-9]+)', value)
    if match:
        seconds = int(match.group(1))
        return seconds*1000 if seconds > 0 else -1
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None: parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return max(0, parsed.timestamp()*1000-time.time()*1000)
    except (ValueError, TypeError, OverflowError): return 0


def _retryable_error(error):
    reason = getattr(error, 'reason', error)
    if isinstance(reason, http.client.RemoteDisconnected): return True
    if isinstance(reason, socket.gaierror): return True
    if isinstance(reason, socket.timeout) or str(reason) == 'Request timed out': return True
    codes = {errno.ECONNRESET, errno.ECONNREFUSED, errno.EPIPE, errno.ETIMEDOUT,
             errno.ENETUNREACH, errno.EHOSTUNREACH, 10054, 10061, 10060, 10051, 10065}
    return getattr(reason, 'errno', None) in codes


class SessionHttpExporter:
    def __init__(self, options, environment=None, tls_context=None):
        self.options = options
        self.config = log_transport_options(options, environment)
        self.tls_context = tls_context
        self._agent_ready = False
        self._selected_agent = None
        self.pending = set()
        self.closed = False
        self._shutdown = None

    async def _ensure_agent(self):
        if self._agent_ready: return
        protocol = urllib.parse.urlsplit(self.options['url']).scheme.lower()+':'
        selected = self.options.get('httpAgentOptions')
        if callable(selected):
            agent = await await_callback_result(selected(protocol))
            self._selected_agent = agent
            context = agent if isinstance(agent, ssl.SSLContext) else getattr(agent, 'ssl_context', None)
            if context is not None: self.tls_context = context
        elif protocol == 'https:' and selected:
            ca = selected.get('ca')
            def pem(value):
                if isinstance(value, list): return b'\n'.join(pem(item) for item in value)
                return value if isinstance(value, bytes) else value.encode('utf-8')
            if ca is not None:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.load_verify_locations(cadata=pem(ca).decode('utf-8'))
            else: context = ssl.create_default_context()
            if selected.get('rejectUnauthorized') is False:
                context.check_hostname = False; context.verify_mode = ssl.CERT_NONE
            if selected.get('ciphers') is not None: context.set_ciphers(selected['ciphers'])
            versions = {'TLSv1': ssl.TLSVersion.TLSv1, 'TLSv1.1': ssl.TLSVersion.TLSv1_1,
                        'TLSv1.2': ssl.TLSVersion.TLSv1_2, 'TLSv1.3': ssl.TLSVersion.TLSv1_3}
            for field, attribute in [('minVersion','minimum_version'),('maxVersion','maximum_version')]:
                if selected.get(field) is not None: setattr(context, attribute, versions[selected[field]])
            if selected.get('cert') is not None:
                # CPython's SSL API loads client identities from files. These
                # owned files disappear immediately after OpenSSL loads them.
                with tempfile.TemporaryDirectory(prefix='dsh-otel-tls-') as directory:
                    cert = Path(directory)/'cert.pem'; cert.write_bytes(pem(selected['cert'])); cert.chmod(0o600)
                    key = None
                    if selected.get('key') is not None:
                        key = Path(directory)/'key.pem'; key.write_bytes(pem(selected['key'])); key.chmod(0o600)
                    context.load_cert_chain(str(cert), None if key is None else str(key), selected.get('passphrase'))
            self.tls_context = context
        self._agent_ready = True

    async def _headers(self):
        headers = await resolve_headers(self.options)
        # SDK Node transport assigns its own User-Agent after explicit headers.
        headers = {key: value for key, value in headers.items() if key.lower() != 'user-agent'}
        agent = self.options.get('userAgent')
        headers['User-Agent'] = (str(agent)+' ' if agent else '')+DEFAULT_USER_AGENT
        return headers

    async def _send(self, payload, timeout):
        await self._ensure_agent()
        headers = await self._headers()
        if self.config['compression'] == 'gzip':
            payload = gzip.compress(payload, mtime=0)
            headers = {key: value for key, value in headers.items() if key.lower() != 'content-encoding'}
            headers['Content-Encoding'] = 'gzip'
        request = urllib.request.Request(self.options['url'], data=payload, headers=headers, method='POST')
        def read(signal):
            # The SDK Node exporter uses its own HTTP agent; it does not inherit
            # an Undici dispatcher, collector headers or TLS environment values.
            with open_stream(request, signal, idle_timeout_ms=min(timeout,2147483647),
                redirect_policy='manual', raise_http_errors=False, tls_context=self.tls_context,
                proxy_policy='direct') as (response, chunks):
                yield dict(status=response.status, reason=str(response.reason), headers=dict(response.headers))
                size = 0
                try:
                    for chunk in chunks:
                        size += len(chunk)
                        if size > MAX_RESPONSE_BODY_SIZE:
                            raise ValueError('OTLP export response body exceeded size limit of 4194304 bytes')
                        yield chunk
                except Exception as error:
                    if getattr(error, 'code', None) == 'TIMEOUT': raise RuntimeError('Request timed out') from None
                    if response.status <= 299 and not isinstance(error, ValueError): return
                    raise
        stream = iter_chunks(OwnedStream(read))
        try:
            metadata = await stream.__anext__()
            async for _ in stream: pass
            return metadata
        except Exception as error:
            if getattr(error, 'code', None) == 'TIMEOUT':
                raise _RetryableTransportError(RuntimeError('Request timed out')) from None
            if _retryable_error(error): raise _RetryableTransportError(error) from None
            raise
        finally: await stream.aclose()

    async def _run(self, payload):
        deadline = time.monotonic()+self.config['timeoutMillis']/1000
        timeout, backoff = self.config['timeoutMillis'], 1000
        response = None
        last_error = None
        for attempt in range(6):
            try:
                response = await self._send(payload, timeout)
                last_error = None
            except _RetryableTransportError as error:
                last_error = error.error
                response = dict(status=0, headers={})
            if last_error is None:
                if response['status'] <= 299: return
                if response['status'] not in (429,502,503,504): raise RuntimeError(response['reason'])
            if attempt == 5: break
            delay = retry_after(next((value for key,value in response['headers'].items() if key.lower()=='retry-after'),None))
            if delay is None: delay = max(0,min(backoff*(0.8+random.random()*0.4),5000))
            backoff *= 1.5
            remaining = (deadline-time.monotonic())*1000
            if delay > remaining: break
            timeout = remaining
            await asyncio.sleep(max(0,delay)/1000)
        if last_error is not None: raise last_error
        raise RuntimeError('Export failed with retryable status')

    def export(self, payload):
        async def run():
            if self.closed: raise RuntimeError('OTLP exporter is shut down')
            if len(self.pending) >= self.config['concurrencyLimit']: raise RuntimeError('Concurrent export limit reached')
            return await self._run(payload)
        promise = CleanupPromise(start_coroutine(run()))
        self.pending.add(promise)
        promise.add_done_callback(lambda _: self.pending.discard(promise))
        return promise

    async def forceFlush(self):
        if self.pending: await asyncio.gather(*list(self.pending), return_exceptions=True)

    def shutdown(self):
        if self._shutdown is not None: return self._shutdown
        self.closed = True
        async def finish(): await self.forceFlush()
        self._shutdown = CleanupPromise(start_coroutine(finish()))
        return self._shutdown
