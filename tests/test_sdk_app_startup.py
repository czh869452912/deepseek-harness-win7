import io
import pytest

from dsh.boot.cmdline import internals, provide_cmdline
from dsh.bundle.sdk_app import SdkAppStartup
from dsh.cordis.context import Context


class Stdin:
    readableEnded = False

    def __init__(self):
        self.listeners = []

    def once(self, event, callback):
        assert event == 'end'
        self.listeners.append(callback)

    on = once

    def off(self, event, callback):
        if callback in self.listeners:
            self.listeners.remove(callback)

    def end(self):
        self.readableEnded = True
        callbacks, self.listeners = self.listeners, []
        for callback in callbacks:
            callback()


class Ready:
    def __init__(self):
        self.callbacks = set()

    def on_ready(self, callback):
        self.callbacks.add(callback)
        return lambda: self.callbacks.discard(callback)

    def commit(self):
        for callback in list(self.callbacks):
            callback()
        self.callbacks.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize('args,code', [(['--help'], 0), (['--unknown'], 1), (['extra'], 1)])
async def test_help_and_invalid_invocations_never_publish_readiness(monkeypatch, args, code):
    output = io.StringIO()
    stdin = Stdin()
    monkeypatch.setattr(internals, 'stdin', stdin)
    monkeypatch.setattr(internals, 'stdout', output)
    monkeypatch.setattr(internals, 'stderr', output)
    ctx, exits = Context(), []
    provide_cmdline(ctx, dict(args=args, exit=exits.append, ready=Ready()))
    await ctx.plugin(SdkAppStartup, {'profile': 'minimal'})
    try:
        assert ctx.get('sdkAppStartup') is None
        assert exits == [code]
        assert not stdin.listeners
        if code == 0:
            assert 'dsh --profile minimal' in output.getvalue()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('dispose_before_ready', [False, True])
async def test_eof_waits_for_commit_and_unload_revokes_pending_exit(monkeypatch, dispose_before_ready):
    stdin, ready, exits = Stdin(), Ready(), []
    monkeypatch.setattr(internals, 'stdin', stdin)
    ctx = Context()
    provide_cmdline(ctx, dict(args=[], exit=exits.append, ready=ready))
    fiber = await ctx.plugin(SdkAppStartup)
    assert ctx.get('sdkAppStartup') == {'accepted': True}
    stdin.end()
    assert not exits
    if dispose_before_ready:
        await fiber.dispose()
    ready.commit()
    assert exits == ([] if dispose_before_ready else [0])
    await ctx.fiber.dispose()
    assert not stdin.listeners and not ready.callbacks
    assert ctx.get('sdkAppStartup') is None
