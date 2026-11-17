from types import SimpleNamespace
import pytest
from dsh.cordis import Context
from dsh.client.appearance_current import CurrentThemeHost,CurrentLocaleHost
from scripts.rc022_appearance_probe import observe


@pytest.mark.asyncio
async def test_live_theme_boot_markup_locale_and_admission():
    rows=await observe();assert len(rows)==28
    assert all(row['idempotent'] for row in rows if row['step']=='family')
    assert all(not row['accepted'] for row in rows if row['step']=='invalid')
    default=next(row for row in rows if row['step']=='default')
    assert [row['kind'] for row in default['rows']]==['style','script','script']
    assert '--dsh-code-font-size' in default['rows'][1]['text']
    assert next(row for row in rows if row['step']=='disposed')['rows']==[dict(kind='script',placement='head',text='after')]


@pytest.mark.asyncio
@pytest.mark.parametrize('plugin',[CurrentThemeHost,CurrentLocaleHost])
async def test_optional_settings_policy_is_owned_and_reversible(plugin):
    ctx=Context();calls=[]
    def configure(value,owner):calls.append(value);return lambda:calls.append('released')
    try:
        ctx.provide('settings',SimpleNamespace(configure=configure))
        fiber=ctx.plugin(plugin,config={});await fiber
        assert calls==[dict(auto=False)]
        await fiber.dispose();assert calls==[dict(auto=False),'released']
    finally:await ctx.fiber.dispose()
