import json
from pathlib import Path

import pytest

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.fiber import FiberState
from scripts.generate_pure_client_hosts import capture
from scripts.rc022_candidate_fixture import setup
from test_rc022_manager_wire import SOURCE


@pytest.mark.asyncio
async def test_all_literal_empty_source_hosts_and_configuration_hosts_mount_through_loader(tmp_path):
    manifest = json.loads((Path(__file__).resolve().parents[1]/'dsh/client/pure_hosts_current.json').read_text(encoding='utf-8'))
    assert capture(SOURCE) == manifest
    specifications = [('client-'+row['name'].split('/dsh-client-', 1)[1], {}) for row in manifest['rows']]
    specifications += [('client-shortcuts', dict(stopSequenceMs=700)), ('client-ui-sidebar-documentpreview', dict(office=dict(maxPending=3), excel=dict(maxCells=1200)))]
    ctx = await setup(tmp_path, extra=specifications)
    try:
        entries = {entry.options['id']:entry for entry in ctx.loader.entries()}
        assert all(entries[name].fiber.state == FiberState.ACTIVE for name, _ in specifications)
        table = []; ctx.emit('webserver/index-inject', table)
        assert {row['name'] for row in table} == {'__DSH_SHORTCUTS_CONFIG__', '__DSH_DOCUMENT_PREVIEW_CONFIG__'}
        assert next(row for row in table if row['name'] == '__DSH_SHORTCUTS_CONFIG__')['value'] == dict(stopSequenceMs=700)
        preview = next(row['value'] for row in table if row['name'] == '__DSH_DOCUMENT_PREVIEW_CONFIG__')
        assert preview['office']['maxPending'] == 3 and preview['office']['maxReaders'] == 32
        assert preview['excel']['maxCells'] == 1200 and preview['excel']['timeoutMs'] == 15000
        for name in ('client-shortcuts', 'client-ui-sidebar-documentpreview'):
            await await_callback_result(ctx.loader.update(entries[name].id, dict(disabled=True)))
        empty = []; ctx.emit('webserver/index-inject', empty); assert empty == []
        (tmp_path/'client-host-observations.json').write_text(json.dumps(dict(activePackages=[row['name'] for row in manifest['rows']], globals=table, afterDisable=empty), indent=2), encoding='utf-8')
    finally:
        await ctx.fiber.dispose()
