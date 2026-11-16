"""Shared modern session setup and outbound envelopes for current transports."""
from dsh.mcp.result_current import project_modern_result


class NegotiatedProtocol:
    async def _initialize(self):
        if self.negotiated['era'] == 'legacy':
            return await super()._initialize()
        discover = self.negotiated['discover']
        self.protocol_version = self.negotiated['version']
        self.server_capabilities = discover['capabilities']
        self.server_info = discover.get('_meta', {}).get('io.modelcontextprotocol/serverInfo')
        self.server_instructions = discover.get('instructions')
        return self

    async def request(self, packet, signal=None, timeout=60000):
        modern = self.negotiated is not None and self.negotiated['era'] == 'modern'
        if modern:
            params = dict(packet.get('params') or {})
            meta = dict(params.get('_meta') or {})
            meta.update({'io.modelcontextprotocol/protocolVersion': self.protocol_version,
                'io.modelcontextprotocol/clientInfo': getattr(self, 'client_info', {'name': 'dsh-mcp-client', 'version': '0.0.1'}),
                'io.modelcontextprotocol/clientCapabilities': {}})
            params['_meta'] = meta
            packet = dict(packet, params=params)
        result = await super().request(packet, signal=signal, timeout=timeout)
        return project_modern_result(packet['method'], result) if modern else result
