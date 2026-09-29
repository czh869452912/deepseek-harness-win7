"""Test-only canonical Web bootstrap. Production has a single profile entry."""
import tempfile
from pathlib import Path
from pytest import MonkeyPatch
from dsh.boot.profile_boot import run_profile


async def web_context(home=None):
    home = Path(home or tempfile.mkdtemp(prefix='dsh-web-test-'))
    environment = MonkeyPatch()
    environment.setenv('DSH_HOME', str(home))
    environment.setenv('DSH_TELEMETRY_MODE', 'DISABLED')
    try:
        result = await run_profile(dict(profile='web', dshHome=str(home), args=['--no-open', '--port', '0'], waitForExit=False))
    except BaseException:
        environment.undo()
        raise
    ctx = result['ctx']
    ctx.effect(lambda: environment.undo)
    ctx._test_shutdown = result['shutdown']
    return ctx


async def close_web_context(ctx):
    ctx._test_shutdown.shutdown(0)
    await ctx._test_shutdown.wait()
