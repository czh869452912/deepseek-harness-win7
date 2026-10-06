import importlib

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('interrupted', (False, True))
async def test_upgrade_fixture_closes_owned_clients_before_loop_exit(monkeypatch, interrupted):
    contract = importlib.import_module('tests.1to1.apps_web.test_webserver_contract')
    original_upgrade = contract.raw_upgrade
    original_register = contract.WebServerService.register_upgrade
    writers = []

    async def tracked_upgrade(*arguments, **keywords):
        reader, writer = await original_upgrade(*arguments, **keywords)
        writers.append(writer)
        return reader, writer

    def register_upgrade(server, path, handler):
        if interrupted and path == '/exact-only/':
            raise RuntimeError('Owned fixture interruption after upgrade')
        return original_register(server, path, handler)

    monkeypatch.setattr(contract, 'raw_upgrade', tracked_upgrade)
    monkeypatch.setattr(contract.WebServerService, 'register_upgrade', register_upgrade)
    try:
        if interrupted:
            with pytest.raises(RuntimeError, match='Owned fixture interruption after upgrade'):
                await contract.test_serves_registered_routes_index_taps_and_the_fallback_seat_semantics()
        else:
            await contract.test_serves_registered_routes_index_taps_and_the_fallback_seat_semantics()
        assert len(writers) == (1 if interrupted else 2)
        assert all(writer.is_closing() for writer in writers)
        for writer in writers:
            await writer.wait_closed()
    finally:
        for writer in writers:
            writer.close()
            await writer.wait_closed()
