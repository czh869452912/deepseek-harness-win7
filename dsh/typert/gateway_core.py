"""Carrier-independent rc022 Gateway core; network admission mounts separately."""
import inspect
from dsh.cordis.service import Service
from dsh.core.abort import AbortController
from dsh.typert.authorized_calls import AuthorizedCallResolver, assert_peer_live
from dsh.typert.dispatch import TypertGatewayError, remote_request, rpc_failure
from dsh.typert.invocation import create_invocation, InvocationStream, cancelled
from dsh.typert.rpc_result import encode_rpc_result


class AuthorizedGatewayCore(Service):
    inject = ['typert', 'remoteAccess']

    def __init__(self, ctx):
        super().__init__(ctx, 'typertGateway')
        self.resolver = AuthorizedCallResolver(ctx)

    async def prepare(self, request):
        prepared = await self.resolver.resolve(request)
        invocation = create_invocation(request, prepared.descriptor, AbortController())
        try:
            method, args = self.resolver.bind(prepared, invocation)
        except BaseException:
            await invocation.close()
            raise
        prepared.method, prepared.args, prepared.invocation = method, args, invocation
        return prepared

    async def invoke(self, request):
        prepared = await self.prepare(request)
        return await self._invoke_prepared(prepared)

    async def _invoke_prepared(self, prepared):
        if prepared.descriptor.get('mode') is not None:
            # Source rejects this carrier before claiming/returning its uplink.
            # Drop Python's strong signal subscriptions (Source uses weak joins).
            prepared.invocation.release_subscriptions()
            raise TypertGatewayError('signature-invalid', prepared.endpoint, 'stream Remote methods must be opened through the stream carrier')
        try:
            try:
                value = prepared.method(*prepared.args)
                return await value if inspect.isawaitable(value) else value
            except Exception as error:
                if prepared.invocation.signal.aborted:
                    raise cancelled(prepared.endpoint, error)
                raise
        finally:
            await prepared.invocation.close()

    async def invoke_rpc(self, endpoint, payload, signal, peer):
        try:
            assert_peer_live(peer, endpoint)
            request = dict(remote_request(endpoint, payload, signal), peer=peer)
            prepared = await self.prepare(request)
            value = await self._invoke_prepared(prepared)
            return encode_rpc_result(value, prepared.descriptor['result'])
        except Exception as error:
            return rpc_failure(error)

    async def stream(self, request):
        prepared = await self.prepare(request)
        if prepared.descriptor.get('mode') != 'stream':
            await prepared.invocation.close()
            raise TypertGatewayError('signature-invalid', prepared.endpoint, 'unary Remote methods cannot be opened through the stream carrier')
        try:
            source = prepared.method(*prepared.args)
        except Exception as error:
            await prepared.invocation.close()
            if prepared.invocation.signal.aborted:
                raise cancelled(prepared.endpoint, error)
            raise
        if not hasattr(source, '__aiter__') and not hasattr(source, '__iter__') or isinstance(source, (str, bytes, dict)):
            await prepared.invocation.close()
            if inspect.iscoroutine(source):
                source.close()
            raise TypertGatewayError('result-invalid', prepared.endpoint, 'stream Remote method did not return Iterable or AsyncIterable', 'result')
        return InvocationStream(source, prepared.endpoint, prepared.invocation)
