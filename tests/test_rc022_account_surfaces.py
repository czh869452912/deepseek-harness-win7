import asyncio
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.client.account_surfaces_current import CurrentUiSettingsAccount
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.settings.forms import SettingsForms
from scripts.rc022_account_surfaces_probe import observe, cases


@pytest.mark.asyncio
async def test_public_account_configuration_admission_and_reversible_effects(tmp_path):
    rows = await observe()
    (tmp_path/'account-surfaces-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == len(cases()) == 315
    assert rows[0]['config']['step'] == 'welcome'
    assert rows[0]['config']['usage'] == 'compact'
    assert rows[0]['calls'] == [dict(policy=dict(auto=False))]
    assert rows[0]['disposed'] == 1 and rows[0]['after'] == []
    assert rows[1]['table'][0]['value'] == dict(notificationPollIntervalMs=600000)
    for row in rows[-3:]:
        assert row['table'][0]['value']['contactSource'] == 'public-source'
        assert 'not-public' not in json.dumps(row['table'])
    assert rows[-2]['calls'] == [dict(policy=dict(auto=False))]
    assert rows[-1]['calls'] == []


@pytest.mark.asyncio
async def test_account_volatile_choices_use_actual_settings_form_and_remove_policy(tmp_path):
    ctx = Context(); entry = None; base = {}; override = {}
    try:
        await ctx.plugin(Loader)
        ctx.set_service('profileContext', dict(home=str(tmp_path)))
        fiber = await ctx.plugin(CurrentUiSettingsAccount, base)
        entry = SimpleNamespace(id='account', options=dict(id='account',
            name='@deepseek-ai/dsh-client-ui-settings-account', config={}), fiber=fiber)
        class Editor:
            documentPath = str(tmp_path/'patch.yml')
            def entries(self): return [entry]
            def configuration(self): return [dict(entry=entry, inherited=base, override=override)]
            async def edit(self, target, change):
                config = change(copy.deepcopy(entry.options['config']), copy.deepcopy(base))
                await fiber.update(config)
                entry.options['config'] = config
                override.clear(); override.update(config)
        ctx.set_service('configEditor', Editor())
        await ctx.plugin(SettingsForms)
        for _ in range(3): await asyncio.sleep(0)
        settings = ctx.settings
        row = settings.describe()[0]
        assert row['autoGenerate'] is False
        assert row['value']['step'] == 'welcome'
        assert 'contactFormUrl' not in row['value']
        await settings.update('account', dict(step='credit', purpose='office'))
        assert fiber.effectiveConfig['step'].get() == 'credit'
        assert settings.describe()[0]['value']['purpose'] == 'office'
        assert fiber.ctx.fiber in settings.presentations
        await fiber.dispose()
        assert fiber.ctx.fiber not in settings.presentations
    finally: await ctx.fiber.dispose()


def test_account_package_metadata_and_locales_match_retained_source_identities():
    root = Path(__file__).resolve().parents[1]
    receipt = json.loads((root/'migration/candidates/rc022/account-surfaces-inputs.json').read_text(encoding='utf-8'))
    assert len(receipt['files']) == 18
    for row in receipt['files']:
        assert hashlib.sha256((root/row['path']).read_bytes()).hexdigest() == row['sha256']
