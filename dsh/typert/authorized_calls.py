"""Prepare resource-authorized calls before resolving any Host identity.

The carrier owns invocation lifetime/uplink; this resolver accepts its invocation
factory after validation, policy admission, receiver and parameter resolution.
"""
import asyncio
import json
from types import SimpleNamespace as NS
from dsh.core.abort import NEVER_ABORTED
from dsh.core.session.json import UNDEFINED
from dsh.typert.artifact import UNDEFINED as CODEC_UNDEFINED
from dsh.typert.access import call_resources
from dsh.typert.current import CurrentRemoteDispatcher
from dsh.typert.dispatch import exact_arguments, decode, binding_of, original_of, TypertGatewayError
from dsh.typert.remote import remote_methods, RemoteError
from dsh.typert.stores import field


def assert_peer_live(peer, endpoint):
    if peer.signal.aborted:
        raise TypertGatewayError('peer-disposed', endpoint, 'the calling Peer has been disposed')


class AuthorizedCallResolver(CurrentRemoteDispatcher):
    def resource_readers(self, row):
        receiver = self.ctx.get(row['service'])
        if receiver is None:
            return None
        member = row.get('implementation', row['method'])
        marker = next((marker for marker in remote_methods(original_of(receiver))
                       if (marker['method'] == member if 'implementation' in row
                           else marker.get('exportName', marker['method']) == member)), None)
        return None if marker is None else marker.get('resources')

    async def resolve(self, request):
        endpoint = request['namespace'] + '/' + request['method']
        peer = request['peer']
        assert_peer_live(peer, endpoint)
        row = self.descriptor(request['namespace'], request['method'], endpoint)
        args = request['args']
        exact_arguments(args, row, endpoint)
        validated = {}
        invocation = row['invocation']
        if invocation['kind'] == 'context':
            validated[invocation['wire']] = args[invocation['wire']]
        for parameter in row['parameters']:
            wire = parameter['wire']
            if wire not in args:
                continue
            value = decode(parameter['codec'], args[wire], endpoint, wire) if parameter['source'] == 'json' else args[wire]
            validated[wire] = UNDEFINED if value is CODEC_UNDEFINED else value
        if field(peer.principal, 'kind') != 'owner':
            resources = call_resources(self.ctx.typert, self.resource_readers(row), row, validated, request.get('signal') or NEVER_ABORTED)
            decision = dict(kind='deny', reason='resource-invalid') if resources is None else self.ctx.remoteAccess.decide(dict(
                principal=peer.principal, action=endpoint, resources=resources, args=validated))
            if decision['kind'] == 'deny':
                reason = decision['reason']
                raise RemoteError('remote-access/denied', 'remote access: %s: access denied (%s)' % (endpoint, reason), dict(action=endpoint, reason=reason))
        context = self.ctx
        if invocation['kind'] == 'context':
            provider = self.ctx.typert.contexts.getHost(invocation['context'])
            # Matching/decoding and activation are all after resource admission.
            label = 'Context provider ' + json.dumps(invocation['context'])
            if provider is None:
                raise TypertGatewayError('context-unavailable', endpoint, label + ' is unavailable')
            if field(provider, 'wire') != invocation['wire'] or invocation['codec']['mode'] == 'strict' and field(provider, 'wireTypeSymbol') != invocation['codec']['typeSymbol']:
                raise TypertGatewayError('provider-mismatch', endpoint, label + ' does not match its strict definition', invocation['wire'])
            identity = decode(invocation['codec'], validated[invocation['wire']], endpoint, invocation['wire'])
            context = await self._resolve(provider, invocation['codec'], identity, invocation['wire'], endpoint, 'context', invocation['context'])
        receiver = context.get(row['service'])
        if receiver is None:
            raise TypertGatewayError('service-unavailable', endpoint, 'active Service "%s" is unavailable' % row['service'])
        binding_of(receiver, row['service'], endpoint, row['namespace'])
        async def parameter_value(parameter):
            wire = parameter['wire']
            if wire not in validated:
                return UNDEFINED
            if parameter['source'] == 'json':
                return validated[wire]
            identity = decode(parameter['codec'], validated[wire], endpoint, wire)
            return await self._resolve(self.ctx.typert.lookups.get(parameter['lookup']), parameter['codec'], identity, wire, endpoint, 'lookup', parameter['lookup'])
        positional = list(await asyncio.gather(*(parameter_value(parameter) for parameter in row['parameters'])))
        return NS(endpoint=endpoint, descriptor=row, context=context, args=positional, request=request)

    def bind(self, prepared, invocation):
        row = prepared.descriptor
        receiver = prepared.context.extend(dict(invocation=invocation)).get(row['service'])
        implementation = row.get('implementation', row['method'])
        if 'implementation' not in row:
            markers = [marker for marker in remote_methods(original_of(receiver))
                       if marker.get('exportName', marker['method']) == row['method']]
            if len(markers) > 1:
                raise TypertGatewayError('ambiguous-endpoint', prepared.endpoint, 'multiple Remote methods export this endpoint')
            if markers:
                implementation = markers[0]['method']
        method = getattr(receiver, implementation, None)
        if not callable(method):
            raise TypertGatewayError('method-unavailable', prepared.endpoint, 'active Service "%s" has no callable method "%s"' % (row['service'], implementation))
        positional = list(prepared.args)
        if 'cancellation' in row:
            positional.append(invocation.signal)
        return method, positional
