"""Compare browser Host configuration validation, globals and effect teardown."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis.context import Context
    from dsh.client.configuration_current import CurrentShortcutsHost, CurrentDocumentPreviewHost
    rows=[]
    cases=[('shortcuts',CurrentShortcutsHost,[{},dict(stopSequenceMs=700),dict(stopSequenceMs=2147483646),dict(stopSequenceMs=0),dict(stopSequenceMs=2147483647),dict(stopSequenceMs=1.5)]),
        ('ui-sidebar-documentpreview',CurrentDocumentPreviewHost,[{},dict(office=dict(maxPending=3),excel=dict(maxCells=1200)),dict(office=dict(maxReaders=0)),dict(excel=dict(timeoutMs=2147483648)),dict(office=dict(maxCachedBytes=9007199254740992))])]
    for slug,plugin,configs in cases:
        for config in configs:
            ctx=Context()
            try:
                try:parsed=plugin.Config(config)
                except Exception:
                    rows.append(dict(slug=slug,config=config,accepted=False));continue
                fiber=await ctx.plugin(plugin,parsed);before=[];ctx.emit('webserver/index-inject',before)
                await fiber.dispose();after=[];ctx.emit('webserver/index-inject',after)
                rows.append(dict(slug=slug,config=config,accepted=True,before=before,after=after))
            finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_client_configuration.mts','Actual original shortcuts/documentpreview Host configuration defaults and bounds, browser globals and reversible page injection.',[Path(__file__).resolve(),ROOT/'dsh/client/configuration_current.py'])
