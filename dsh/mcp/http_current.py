"""Current streamable HTTP: in-place era probe and SDK 2 request headers."""
import asyncio
import base64
import json

from dsh.host.http_proxy_policy import JS_SPACE
from dsh.mcp.http_client import StreamableHttpMcpClient
from dsh.mcp.negotiated_protocol_current import NegotiatedProtocol
from dsh.mcp.negotiation_current import SdkError, SdkHttpError
from dsh.mcp.probe_current import negotiate_era, disarm_spent_close_guard
from dsh.mcp.current import RESOURCE_SCHEMAS
from dsh.mcp.schemas import parse


def encode_mcp_param_value(value):
    plain = value == value.strip(JS_SPACE) and not (value.startswith('=?base64?') and value.endswith('?='))
    plain = plain and all(char == '\t' or 32 <= ord(char) <= 126 for char in value)
    if plain:
        return value
    encoded = value.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'replace').encode('utf-8')
    return '=?base64?' + base64.b64encode(encoded).decode('ascii') + '?='


class _HttpProbeChannel:
    def __init__(self, client):
        self.client = client
        self.onmessage = self.onclose = None
        self.onerror = client.on_error

    async def start(self):
        pass

    async def send(self, packet):
        await self.client._send(packet)


class CurrentStreamableHttpMcpTransport(NegotiatedProtocol, StreamableHttpMcpClient):
    def __init__(self, url, headers=None, negotiation=None):
        super().__init__(url, headers)
        self.negotiation = negotiation if negotiation is not None else dict(kind='auto', modernVersions=['2026-07-28'], fallbackAvailable=True, probe={})
        self.negotiated = None
        self._probing = False
        self._probe_channel = None

    async def _initialize(self):
        channel = self._probe_channel = _HttpProbeChannel(self)
        self._probing = True
        try:
            self.negotiated = await negotiate_era(self.negotiation, channel, transport_kind='http', client_info=getattr(self, 'client_info', None))
        finally:
            self._probing = False
            disarm_spent_close_guard(channel)
        return await super()._initialize()

    async def _receive(self, packet):
        packet = parse('CurrentMessageEnvelope',packet,RESOURCE_SCHEMAS)
        if self._probing:
            if self._probe_channel.onmessage is not None:
                self._probe_channel.onmessage(packet)
            return
        await super()._receive(packet)

    def _disconnect(self):
        if not self._closed and self._probing and self._probe_channel.onclose is not None:
            self._probe_channel.onclose()
        super()._disconnect()

    def _common_headers(self):
        headers = dict(self.headers)
        if self.session_id:
            headers['mcp-session-id'] = self.session_id
        if self.protocol_version:
            headers['mcp-protocol-version'] = self.protocol_version
        return headers

    async def _send(self, packet):
        response = None
        try:
            headers = self._common_headers()
            params = packet.get('params') or {}
            meta = params.get('_meta') or {}
            version = meta.get('io.modelcontextprotocol/protocolVersion')
            if isinstance(version, str) and 'id' in packet and 'method' in packet:
                headers['mcp-protocol-version'] = version
                headers['mcp-method'] = packet['method']
                field = {'tools/call':'name', 'prompts/get':'name', 'resources/read':'uri',
                    'tasks/get':'taskId', 'tasks/update':'taskId', 'tasks/cancel':'taskId'}.get(packet['method'])
                if field is not None and isinstance(params.get(field), str):
                    headers['mcp-name'] = encode_mcp_param_value(params[field])
            handshake = packet.get('method') == 'initialize'
            if handshake:
                headers.pop('mcp-session-id', None)
            accepted = [item.strip().lower() for item in headers.get('accept','').split(',') if item.strip()]
            headers.update({'content-type':'application/json', 'accept':', '.join(dict.fromkeys(accepted+['application/json','text/event-stream']))})
            body = json.dumps(packet,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode('utf-8')
            response = await self._request_http('POST',headers,body)
            if handshake and 200 <= response.status < 300:
                self.session_id = response.headers.get('mcp-session-id') or None
            if not 200 <= response.status < 300:
                text = (await response.read()).decode('utf-8',errors='replace')
                if response.status == 400 and isinstance(version,str) and version >= '2026-07-28':
                    try:
                        error_packet = json.loads(text)
                        parse('ProbeErrorEnvelope',error_packet,RESOURCE_SCHEMAS)
                    except (ValueError,TypeError):
                        pass
                    else:
                        await self._receive(error_packet)
                        return
                raise SdkHttpError('CLIENT_HTTP_NOT_IMPLEMENTED','Error POSTing to endpoint: '+text,
                    dict(status=response.status,statusText=response.reason,text=text))
            if response.status == 202:
                await response.read()
                if packet.get('method') == 'notifications/initialized':
                    self._owned(self._get_sse())
                return
            if 'method' not in packet or 'id' not in packet:
                await response.read()
                return
            content_type = response.headers.get('content-type')
            media = content_type.split(';',1)[0].strip().lower() if content_type else None
            if media == 'text/event-stream':
                await self._sse(response,False)
            elif media == 'application/json':
                value = json.loads((await response.read()).decode('utf-8-sig',errors='replace'))
                for message in value if isinstance(value,list) else [value]:
                    await self._receive(message)
            else:
                await response.read()
                raise SdkError('CLIENT_HTTP_UNEXPECTED_CONTENT','Unexpected content type: '+(content_type if content_type is not None else 'null'),dict(contentType=content_type))
        except Exception as error:
            if not self._closed:
                self._callback(self._probe_channel.onerror if self._probing else self.on_error,error)
            raise
        finally:
            if response is not None:
                await self._release_writer(response.writer)

    has_per_request_stream = True

    async def _write(self, packet):
        # The SDK request transaction owns this particular HTTP stream. Its
        # cancellation must release the stream without stopping sibling calls.
        await self._send(packet)

    async def _close(self):
        self._disconnect()
        requests = list(getattr(self,'_request_sends',()))
        for task in requests:
            if not task.done():task.cancel()
        await asyncio.gather(*requests,return_exceptions=True)
        tasks = list(getattr(self._probe_channel,'_probe_send_tasks',()))
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await super()._close()
        if self._probe_channel is not None:
            disarm_spent_close_guard(self._probe_channel)
