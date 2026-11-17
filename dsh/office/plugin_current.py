"""Own the default Office carrier beside the unchanged application service."""
import asyncio
from pathlib import Path

from dsh.cordis.plugin import Plugin
from dsh.cordis.service import Service
from dsh.core.cleanup import CleanupPromise
from .browser_engine import BrowserOfficeEngine
from .current import CurrentOfficeKit, KIT_HINT
from .errors import OfficeKitError
from .file_transaction import disk_call


def installed_runtime():
    """Only a prepared local distribution is a production runtime candidate."""
    import ctypes
    architecture = 'x86' if ctypes.sizeof(ctypes.c_void_p) == 4 else 'x64'
    root = Path(__file__).with_name('bin') / architecture
    # The runtime preparation/build layer owns its exact binary inventory.
    # Do not discover development observers, a user browser or an installed Node.
    from .runtime_inputs import verify_installed_runtime
    return verify_installed_runtime(root, architecture)


class CurrentOfficeEngine(Service):
    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'officeKitEngine')
        self.loading, self.engine, self.closing = None, None, None
        self.reported = set()
        ctx.effect(lambda: self.close)

    async def createConverter(self, options=None):
        if self.closing is not None:
            raise OfficeKitError('unavailable', 'The Office engine is closed.')
        if self.loading is None:
            async def load():
                try:
                    runtime = await disk_call(installed_runtime)
                    engine = BrowserOfficeEngine(runtime['executable'], runtime['package'])
                    self.engine = engine
                    return engine
                except (OSError, ValueError, OfficeKitError) as cause:
                    message = 'LibreOffice Kit runtime is unavailable. ' + KIT_HINT
                    if message not in self.reported:
                        self.reported.add(message)
                        self.ctx.logger.warn(message)
                    raise OfficeKitError('unavailable', message, cause=cause) from None
            self.loading = CleanupPromise(load())
            def reset(done):
                if done.cancelled() or done.exception() is not None:
                    self.loading = None
            self.loading.add_done_callback(reset)
        engine = await self.loading
        if self.closing is not None:
            raise OfficeKitError('unavailable', 'The Office engine is closed.')
        return await engine.createConverter(options)

    def close(self):
        if self.closing is None:
            async def close():
                if self.loading is not None:
                    await asyncio.gather(self.loading.task, return_exceptions=True)
                if self.engine is not None:
                    await self.engine.close()
            self.closing = CleanupPromise(close())
        return self.closing


class CurrentOfficeKitPlugin(Plugin):
    Config = CurrentOfficeKit.Config

    def apply(self, ctx):
        if ctx.get('officeKitEngine') is None:
            ctx.plugin(CurrentOfficeEngine)
        ctx.plugin(CurrentOfficeKit, self.config)
