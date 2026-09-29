"""SDK transport owner; reply and flush before whole-runtime shutdown."""
import asyncio
import sys

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.sdk.server import HarnessSdkJsonRpcServer
from dsh.sdk.transport import JsonRpcLineTransport
from dsh.sdk.stdio import StdioInput


class SdkJsonRpcPlugin(Plugin):
    id = 'sdk-jsonrpc-server'
    inject = ['agents']
    Config = Schema.object({'maxTokensAsSuccess': Schema.boolean().default(False)})

    def apply(self, ctx):
        config = self.config
        stream = config.get('input') or ctx.get('sdkStdin')
        owned_stream = stream is None
        if stream is None:
            stream = StdioInput(sys.stdin)
        output = config.get('output') or sys.stdout
        exit_fn = config.get('exit') or ctx.get('appExit')
        if exit_fn is None:
            raise RuntimeError('SDK server requires the launcher appExit service')
        transport = JsonRpcLineTransport(stream, output)
        server = HarnessSdkJsonRpcServer(ctx, transport, config)
        exit_task = [None]

        async def dispose_and_exit():
            try:
                await transport.flush()
            finally:
                try:
                    await ctx.root.fiber.dispose()
                finally:
                    exit_fn(0)

        def schedule_exit():
            if exit_task[0] is None:
                exit_task[0] = asyncio.create_task(dispose_and_exit())

        async def request(method, params):
            if method == 'initialize':
                loader = ctx.get('loader')
                if loader is not None:
                    await loader.await_()
            result = await server.handle_request(method, params)
            if method == 'shutdown':
                # The handler returns and writes its response synchronously
                # before this next-loop callback starts the flush barrier.
                asyncio.get_running_loop().call_soon(schedule_exit)
            return result

        async def cleanup():
            try:
                await server.shutdown()
            finally:
                transport.close()
                if owned_stream:
                    await stream.close()

        transport.on_request(request)
        transport.start()
        ctx.effect(lambda: cleanup)
