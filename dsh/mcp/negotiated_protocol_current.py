"""Shared modern session setup and outbound envelopes for current transports."""
import time
from dsh.mcp.result_current import decode_modern_result, project_modern_result
from dsh.mcp.input_required_current import manual_result, pace_state_only, reject_unhandled_input
from dsh.mcp.negotiation_current import SdkError
from dsh.cordis.utils import _js_own_enumerable_keys


def now_ms():
    return int(time.time() * 1000)


class NegotiatedProtocol:
    async def _request_leg(self, packet, signal, timeout, options):
        return await super().request(packet, signal=signal, timeout=timeout)

    async def _initialize(self):
        if self.negotiated['era'] == 'legacy':
            return await super()._initialize()
        discover = self.negotiated['discover']
        self.protocol_version = self.negotiated['version']
        self.server_capabilities = discover['capabilities']
        self.server_info = discover.get('_meta', {}).get('io.modelcontextprotocol/serverInfo')
        self.server_instructions = discover.get('instructions')
        return self

    def _validate_result(self, method, result):
        if self.negotiated is not None and self.negotiated['era'] == 'modern':
            return result
        return super()._validate_result(method, result)

    async def request(self, packet, signal=None, timeout=60000, request_options=None):
        modern = self.negotiated is not None and self.negotiated['era'] == 'modern'
        if not modern:
            return await super().request(packet, signal=signal, timeout=timeout)
        options = request_options or {}
        flow_started = now_ms()
        leg_options = dict(options)
        config = getattr(self, 'input_required', {})
        max_rounds = config.get('maxRounds', 10)
        original = packet
        round_number = 0
        while True:
            params = dict(packet.get('params') or {})
            meta = dict(params.get('_meta') or {})
            meta.update({'io.modelcontextprotocol/protocolVersion': self.protocol_version,
                'io.modelcontextprotocol/clientInfo': getattr(self, 'client_info', {'name': 'dsh-mcp-client', 'version': '0.0.1'}),
                'io.modelcontextprotocol/clientCapabilities': {}})
            params['_meta'] = meta
            result = await self._request_leg(dict(packet, params=params), signal, timeout, leg_options)
            decoded = decode_modern_result(packet['method'], result)
            if decoded['kind'] != 'input_required':
                return project_modern_result(packet['method'], result)
            if options.get('allowInputRequired'):
                return manual_result(decoded)
            if not config.get('autoFulfill', True):
                return project_modern_result(packet['method'], result)
            round_number += 1
            if round_number > max_rounds:
                last = dict(inputRequests=decoded['inputRequests'])
                if 'requestState' in decoded:
                    last['requestState'] = decoded['requestState']
                raise SdkError('INPUT_REQUIRED_ROUNDS_EXCEEDED', "Multi-round-trip request '"+packet['method']+"' still required input after "+str(max_rounds)+' rounds (inputRequired.maxRounds)', dict(rounds=max_rounds, lastResult=last))
            progress = options.get('onprogress')
            if progress is not None:
                progress(dict(progress=round_number, message="Fulfilling input required by '"+packet['method']+"' (round "+str(round_number)+')'))
            requests = decoded['inputRequests']
            if requests:
                # No input capabilities/handlers are advertised by this host.
                for key in _js_own_enumerable_keys(requests):
                    reject_unhandled_input(key, requests[key])
            else:
                await pace_state_only(signal)
            leg_options = {key:options[key] for key in ('signal','onprogress','resetTimeoutOnProgress','headers','timeout') if key in options}
            leg_options['allowInputRequired'] = True
            if 'maxTotalTimeout' in options:
                elapsed = now_ms() - flow_started
                remaining = options['maxTotalTimeout'] - elapsed
                if remaining <= 0:
                    raise SdkError('REQUEST_TIMEOUT', 'Maximum total timeout exceeded',
                        dict(maxTotalTimeout=options['maxTotalTimeout'],totalElapsed=elapsed))
                leg_options['maxTotalTimeout'] = remaining
            retry = dict(original.get('params') or {})
            if 'requestState' in decoded:
                retry['requestState'] = decoded['requestState']
            packet = dict(original, params=retry)
