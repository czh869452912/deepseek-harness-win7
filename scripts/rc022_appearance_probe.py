"""Live theme/locale Host configuration and exact theme boot markup."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


FAMILIES=['',',,','serif, SANS-SERIF, ui-monospace','MesloLGS NF, "Iosevka", system-ui',
    '</script>,a\\b,\"c\'d','a\t\n\r b,\x00\x7f', '\ufeffA\u00a0B\u2028C\u3000D\ufeff', '\x85A\x85, \u180eB',
    '中文 字体, emoji','a,,b,','"a, b"','monospace, -apple-system, BlinkMacSystemFont']


async def observe():
    from dsh.cordis import Context,Loader
    from dsh.client.appearance_current import CurrentThemeHost,CurrentLocaleHost,normalize_font_family
    from dsh.cordis.utils import _UNDEFINED
    rows=[dict(step='family',input=value,output=normalize_font_family(value),idempotent=normalize_font_family(normalize_font_family(value))==normalize_font_family(value)) for value in FAMILIES]
    ctx=Context();loader=Loader(ctx);ctx.set_service('loader',loader)
    ctx.on('webserver/index-inject',lambda table,*_:table.append(dict(kind='script',placement='head',text='after')))
    try:
        for name,plugin in [('theme',CurrentThemeHost),('locale',CurrentLocaleHost)]:loader.register_plugin_class(name,plugin)
        key=await loader.create(dict(name='theme',config={}));entry=loader.resolve(key);fiber=entry.fiber;await fiber
        def collect():
            table=[];ctx.emit('webserver/index-inject',table,dict(principal=dict(kind='owner')));return table
        rows.append(dict(step='default',rows=collect()))
        for value in [dict(preference='dark',fontSize=22,codeFontSize=16,terminalFontSize=20,textFontFamily=FAMILIES[4],codeFontFamily='Iosevka',terminalFontFamily='MesloLGS NF'),dict(preference='light',fontSize=10)]:
            await entry.update(dict(config=value));await entry.fiber
            rows.append(dict(step='updated',sameFiber=entry.fiber is fiber,rows=collect()))
        for value in [dict(preference='sepia'),dict(fontSize=9),dict(fontSize=23),dict(codeFontSize=17),dict(terminalFontSize=9),dict(fontSize=14.5)]:
            try:fiber.resolveConfig(value);accepted=True
            except Exception:accepted=False
            rows.append(dict(step='invalid',input=value,accepted=accepted))
        await fiber.dispose();rows.append(dict(step='disposed',rows=collect()))
        key=await loader.create(dict(name='locale',config={}));entry=loader.resolve(key);fiber=entry.fiber;await fiber
        for value in [{},dict(preference='en'),dict(preference='pt-BR'),dict(preference='zh-Hant-TW'),dict(preference='bad locale'),dict(preference='123')]:
            try:
                config=fiber.resolveConfig(value);preference=config['preference'].get();answer=dict(accepted=True,value={} if preference is _UNDEFINED else dict(preference=preference))
            except Exception:answer=dict(accepted=False)
            rows.append(dict(step='locale',input=value,**answer))
    finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    import json
    path=output/'families.json';path.write_text(json.dumps(FAMILIES,ensure_ascii=True),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_appearance.mts','Live theme Config, exact ordered head/body boot rows, per-role font bounds, JS whitespace and unsafe-family filtering, disposal and open locale identifiers.',[Path(__file__).resolve(),ROOT/'dsh/client/appearance_current.py'],prepare=prepare)
