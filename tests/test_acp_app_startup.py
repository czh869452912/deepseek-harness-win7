import io

import pytest

from dsh.boot.cmdline import internals, provide_cmdline
from dsh.bundle.acp_app import AcpAppStartup
from dsh.cordis.context import Context
from test_sdk_app_startup import Ready, Stdin


@pytest.mark.asyncio
@pytest.mark.parametrize('args,code', [(['--help'], 0), (['--unknown'], 1), (['extra'], 1)])
async def test_acp_help_and_usage_errors_do_not_claim_transport(monkeypatch, args, code):
    stdin, output, exits = Stdin(), io.StringIO(), []
    monkeypatch.setattr(internals, 'stdin', stdin)
    monkeypatch.setattr(internals, 'stdout', output)
    monkeypatch.setattr(internals, 'stderr', output)
    ctx = Context()
    provide_cmdline(ctx, {'args': args, 'exit': exits.append, 'ready': Ready()})
    try:
        await ctx.plugin(AcpAppStartup)
        assert ctx.get('acpAppStartup') is None
        assert ctx.get('acpStdin') is None
        assert exits == [code] and not stdin.listeners
        if code == 0:
            assert 'dsh --profile acp' in output.getvalue()
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('dispose_before_ready', [False, True])
async def test_acp_eof_waits_for_successful_boot_and_unload_revokes_exit(monkeypatch, dispose_before_ready):
    stdin, ready, exits = Stdin(), Ready(), []
    monkeypatch.setattr(internals, 'stdin', stdin)
    ctx = Context()
    provide_cmdline(ctx, {'args': [], 'exit': exits.append, 'ready': ready})
    fiber = await ctx.plugin(AcpAppStartup)
    assert ctx.get('acpAppStartup') == {'accepted': True}
    assert ctx.get('acpStdin') is stdin
    stdin.end()
    assert not exits
    if dispose_before_ready:
        await fiber.dispose()
    ready.commit()
    assert exits == ([] if dispose_before_ready else [0])
    await ctx.fiber.dispose()
    assert not stdin.listeners and not ready.callbacks
    assert ctx.get('acpAppStartup') is None and ctx.get('acpStdin') is None
